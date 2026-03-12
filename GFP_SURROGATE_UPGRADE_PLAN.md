# GFP 评分与代理模型升级实施指南

这份文档面向当前仓库 `esm3-agent`，目标是把现有的启发式 GFP 评分，逐步升级为：

1. **有结构依据的代理分**：先用 ESMFold / ESM3 结构预测输出的 `pLDDT`、`pTM` 等指标，替换当前基于氨基酸比例的启发式打分。
2. **有实验数据支撑的监督代理模型**：引入 GFP 公开突变-表型数据集，训练荧光预测模型。
3. **主动学习闭环**：把湿实验结果回写到 memory，持续更新代理模型和采样策略。

你的三层计划方向是对的，而且建议严格按 **第一层 → 第二层 → 第三层** 的顺序推进，不要一开始就跳到主动学习。原因很简单：

- 第一层改造成本最低，马上就能提升当前系统的可解释性；
- 第二层才开始让分数和真实实验表型建立联系；
- 第三层依赖前两层已经稳定，否则闭环会把错误放大。

---

## 1. 先看当前仓库里已经有什么

当前评分链路已经存在，只是分数本身还比较启发式：

- `protein_agent/tools/protein_score.py`
  - 当前真正的评分入口。
  - 现在主要使用疏水比例、带电比例、`GSTY` 比例和一个 `structure.confidence` 混合成分数。
- `protein_agent/agent/executor.py`
  - `evaluate(sequence)` 里先调用结构预测，再调用 `protein_score`。
  - 这是后续替换评分后端的最佳接入点。
- `protein_agent/agent/workflow.py`
  - 每轮迭代把 `score`、`structure_data`、`metrics` 写入 `ExperimentMemory`。
  - 这是后续保存 `pLDDT / pTM / surrogate prediction / uncertainty / wet-lab label` 的地方。
- `protein_agent/esm3_integration/bridge.py`
  - 目前已经兼容了 `confidence` 和 `plddt` 字段，说明结构指标规范化层已经有雏形。
  - 非常适合扩展成统一输出 `mean_plddt`、`ptm`、`iptm`、`per_residue_plddt`。
- `protein_agent/workflows/gfp_optimizer.py`
  - 内置 GFP scaffold，当前 scaffold 长度是 **238 aa**。
  - 该 scaffold 的第 **65-67 位** 实际上就是 `SYG`，和你提出的色团核心位点一致。

结论：**架子是现成的，不需要重写 workflow，重点是把“结构输出 schema”和“评分逻辑”升级。**

---

## 2. 总体路线图

建议把项目分成三个里程碑：

### Milestone 1：结构代理分替换启发式分

目标：不依赖湿实验数据，先把现有 `protein_score` 从“氨基酸比例启发式”改成“结构质量驱动”。

### Milestone 2：实验数据监督代理模型

目标：用 GFP 公共数据训练一个荧光预测器，输出比结构代理更接近真实实验表型的分数。

### Milestone 3：主动学习闭环

目标：设计候选 → 预测打分 → 选 top-k → 湿实验 → 回写 memory → 重训模型 → 下一轮设计。

推荐顺序是：

1. 先把结构 score 做稳定；
2. 再把 supervised surrogate 接到线上；
3. 最后再加入 uncertainty-aware 实验选择。

---

## 3. 第一层：把当前启发式评分换成结构代理分

这一层是最应该立刻做的，因为它不依赖任何新实验数据，而且会直接提升当前系统的科学性。

### 3.1 目标

把当前这类启发式：

- 疏水残基比例
- 带电残基比例
- `GSTY` 残基比例
- 一个模糊的 `structure_confidence`

替换成更有解释力的结构代理：

- `mean_pLDDT`
- `pTM`
- `ipTM`（保留接口；如果当前是单体 GFP，可以先不参与打分）
- 色团核心位点约束（`S65-Y66-G67`）
- 可选：Rosetta `REU`

### 3.2 先明确一个关键科学细节

#### pLDDT 是第一优先级

如果你现在只能稳定拿到一个结构质量指标，那就先用 `mean_pLDDT`。

原因：

- 它最容易从结构预测接口获得；
- 是逐残基置信度，解释性强；
- 对筛掉明显折叠差的候选很有效。

#### pTM 是第二优先级

`pTM` 更偏向全局拓扑正确性，适合补充 `mean_pLDDT` 的局部视角。

建议：

- 单体 GFP 场景下，主用 `mean_pLDDT + pTM`；
- 如果某些后端拿不到 `pTM`，不要报错，允许回退到 `mean_pLDDT`。

#### ipTM 不要在单体 GFP 上硬上

`ipTM` 主要是界面质量指标，更适合多聚体或复合物设计。

因此：

- 当前单体 GFP 优化里，`ipTM` 应该作为 **预留字段**；
- 只有以后扩展到 dimer/interface 设计，再把 `ipTM` 纳入主分数。

#### Rosetta REU 很有价值，但不要一开始全量跑

Rosetta `REU` 适合作为稳定性代理，但有两个现实问题：

- 计算成本高；
- 工程集成复杂度高于 `pLDDT/pTM`。

所以第一层的建议不是“全候选都跑 Rosetta”，而是：

- **先把 Rosetta 设计成 top-N rerank 的可选模块**；
- 例如每轮只对结构代理分前 5~10 个候选做 `REU` 重排。

### 3.3 代码上具体怎么改

#### Step 1：统一结构输出 schema

优先改 `protein_agent/esm3_integration/bridge.py` 的结构归一化逻辑，把当前：

- `confidence`
- `plddt`

扩展成一个明确的结构字典，例如：

```python
{
    "structure": ...,
    "confidence": 0.84,
    "mean_plddt": 82.1,
    "per_residue_plddt": [...],
    "ptm": 0.71,
    "iptm": None,
    "pae": None,
    "backend": "esmfold_or_esm3",
}
```

这里的原则是：

- **字段允许为空，但 schema 要稳定**；
- 评分层不要再猜测到底该读 `confidence` 还是 `plddt`；
- 所有结构后端都统一映射到同一套字段名。

#### Step 2：重写 `protein_score.py`

把它从“启发式比例打分器”，改成“结构代理评分器”。

建议输出同时包含：

- `score`：最终单值分数，供 workflow 排序；
- `metrics`：所有原始指标和归一化指标；
- `score_breakdown`：每个分量对总分的贡献，便于调参与审计。

推荐的最小可行公式：

```text
plddt_norm = clip(mean_plddt / 100, 0, 1)
ptm_norm   = clip(ptm, 0, 1)

structure_score =
    0.70 * plddt_norm +
    0.30 * ptm_norm

final_score =
    structure_score
    - motif_penalty
    - length_penalty
```

其中：

- `motif_penalty`
  - 若第 65-67 位不是 `SYG`，则直接给大惩罚；
  - 如果你想更强硬，甚至可以直接把候选标记为 `invalid_candidate=True`。
- `length_penalty`
  - 如果当前 GFP workflow 不允许 indel，那么长度偏离 238 aa 的候选应该降权；
  - 如果后面允许插删，则需要改成“对 scaffold 对齐后再判断色团位点”。

#### Step 3：把色团约束写成显式规则，不要藏在 prompt 里

这是很重要的一点。

不要只在 prompt 中写“尽量保留 motif”，要在评分函数或过滤器里硬编码约束。

推荐逻辑：

1. 当前 GFP scaffold 长度固定时：
   - 直接检查 `sequence[64:67] == "SYG"`；
2. 如果未来允许 indel：
   - 先对齐到 canonical GFP scaffold；
   - 再把 65-67 位映射回来检查。

这样做的好处：

- 行为稳定；
- 不依赖模型“听懂” prompt；
- 审计时能准确解释为什么某个候选被降权。

#### Step 4：把评分细节写入 memory

改造 `ExperimentRecord.metadata`，至少记录：

- `mean_plddt`
- `ptm`
- `iptm`
- `motif_intact`
- `motif_penalty`
- `length_penalty`
- `score_backend`
- `score_version`

这样后续你才能回答这些问题：

- 为什么这轮 top1 高于 top2？
- 是 `pLDDT` 驱动的，还是 motif 约束驱动的？
- 某一轮分数突然变化，是模型更新了还是规则更新了？

#### Step 5：把 Rosetta 作为异步 rerank 模块接入

建议不要把 Rosetta 写进当前同步 `evaluate()` 主路径，而是拆成二阶段：

1. `executor.evaluate(sequence)` 先返回结构代理分；
2. 对 top-N 再调用 Rosetta 打分；
3. 用 `rerank_score = a * structure_score + b * reu_score_norm` 做重排。

推荐做法：

- 新增一个独立工具，例如 `protein_agent/tools/rosetta_score.py`；
- 接收 PDB 或结构对象；
- 输出 `reu_total`、`fa_atr`、`fa_rep` 等你关心的能量分项；
- 初期只在离线 benchmark 和 top-N 精排里使用。

### 3.4 第一层建议增加的配置项

建议在 `protein_agent/config/settings.py` 增加以下环境变量：

- `PROTEIN_AGENT_SCORING_BACKEND=structure`
- `PROTEIN_AGENT_REQUIRE_GFP_CHROMOPHORE=true`
- `PROTEIN_AGENT_GFP_REFERENCE_LENGTH=238`
- `PROTEIN_AGENT_GFP_CHROMOPHORE_START=65`
- `PROTEIN_AGENT_USE_ROSETTA=false`
- `PROTEIN_AGENT_ROSETTA_TOPN=5`

这样做可以避免后续所有逻辑都写死在代码里。

### 3.5 第一层的验收标准

第一层做完后，系统至少要满足：

1. API 返回的每个候选都能看到 `mean_plddt` 和 `ptm`；
2. `protein_score` 不再依赖氨基酸比例启发式作为主分数；
3. 破坏 `SYG` 位点的候选会被显著惩罚或直接过滤；
4. `ExperimentMemory` 里能追溯每个候选的分数构成；
5. 即便后端只返回 `pLDDT` 而没有 `pTM`，系统也能正常运行。

---

## 4. 第二层：引入 GFP 实验数据，训练监督代理模型

这一层是让“分数开始真正接近实验表型”的关键。

核心思想是：

- 不再只预测“结构像不像能折起来”；
- 而是直接预测“这个变体在实验上亮不亮”。

### 4.1 目标

训练一个轻量 surrogate model：

- 输入：GFP 变体序列的 ESM3 embedding（可加少量手工特征）；
- 输出：预测荧光强度或其变换值；
- 推理时替代当前启发式 `score`，或者与结构代理分做加权融合。

### 4.2 数据集怎么用

你提到的两个来源是合理的：

- `Sarkisyan et al. 2016`：优先级最高，先做这个；
- `ProteinGym`：作为补充 benchmark 或外部验证集。

建议的数据目录结构：

```text
data/
  gfp/
    raw/
      sarkisyan_2016.csv
      proteingym_gfp.csv
    interim/
      merged.csv
      cleaned.csv
    processed/
      train.parquet
      valid.parquet
      test.parquet
models/
  gfp_surrogate/
    xgb_v1/
    mlp_v1/
```

### 4.3 数据清洗步骤

这一部分非常关键，很多代理模型做坏，不是模型不行，而是数据清洗出了问题。

#### Step 1：统一 wild-type scaffold

你必须先明确：

- 训练数据里的 wild-type 是哪个 GFP 版本；
- 仓库当前 scaffold 是哪个版本；
- 编号体系是否一致。

如果编号不一致，后面所有 `65-67` 位约束都会漂移。

推荐做法：

- 在数据预处理脚本里固定一条 `reference_sequence`；
- 所有 mutation annotation 都映射到这条 reference 上；
- 输出标准字段：`sequence`, `mutations`, `num_mutations`, `reference_name`。

#### Step 2：过滤不合法样本

建议过滤：

- 含 stop codon 的序列；
- 非标准氨基酸字符；
- 严重缺失 label 的样本；
- 和 reference 长度严重不一致、又无法合理对齐的样本。

#### Step 3：处理重复样本和噪声标签

如果同一序列有多次测量：

- 保留重复测量次数；
- 对 label 取均值或中位数；
- 额外生成 `label_std`，供后续 uncertainty 校准使用。

#### Step 4：定义模型标签

建议不要直接用原始荧光值，优先考虑：

- `log_fluorescence`
- 或 z-score 标准化后的亮度值

原因：

- 回归更稳定；
- 极端亮度值不会把训练拉偏；
- 更适合不同批次之间做归一化。

### 4.4 特征工程怎么做

这里你的方向是对的：**优先使用 ESM3 的 frozen embedding**。

推荐路线：

#### Step 1：提取序列 embedding

新增一个离线特征脚本，例如：

- `scripts/prepare_gfp_dataset.py`
- `scripts/extract_gfp_embeddings.py`

输出：

- 每条序列一个固定维度向量；
- 推荐先用 mean-pooled residue embedding；
- 保存成 `parquet` 或 `npz`，不要每次训练都现场跑 embedding。

#### Step 2：拼接少量结构化特征

除了 embedding，建议额外拼这些简单特征：

- `num_mutations`
- `motif_intact`
- `mean_plddt`（如果你愿意先离线批量预测）
- `ptm`
- `sequence_length`

这样可以让模型同时看到：

- 深度语义特征；
- 规则层面非常关键的强信号。

### 4.5 模型选择顺序

建议不要一开始就上很重的端到端微调，先做轻量 baseline：

#### Baseline A：XGBoost

优点：

- 对中小规模数据很稳；
- 训练快；
- 对 frozen embedding 非常友好；
- 做 feature importance 和 ablation 比较方便。

#### Baseline B：小型 MLP

适合在你确认 embedding 有效后继续提升性能。

推荐结构：

- 2~3 层全连接；
- hidden size 不要太大；
- dropout 打开；
- 输出单值回归。

#### 不建议一开始做的事

- 不要先微调 ESM3 全模型；
- 不要先上过重的多任务训练；
- 不要先引入复杂生成式 reward model。

先把一个能稳定优于结构启发式的轻量模型做出来最重要。

### 4.6 数据切分要避免信息泄漏

这是第二层里最容易被忽略的问题。

如果你随机切分数据，训练集和测试集很可能只差 1~2 个突变，最后分数会虚高。

建议至少做两套评估：

#### Split A：随机切分

用于快速调参，不作为最终结论。

#### Split B：按突变距离或突变数切分

例如：

- 训练：单突变、双突变、部分三突变；
- 测试：高阶多突变；

或者：

- 按和 reference 的编辑距离分桶；
- 留出最远的一桶做测试。

这样更接近真实设计场景：**模型要对“没有见过的组合突变”也有一定泛化能力。**

### 4.7 第二层的线上接入方式

建议新增一个独立模块，而不是继续把所有逻辑都塞进 `protein_score.py`。

推荐新增目录：

```text
protein_agent/
  surrogate/
    dataset.py
    features.py
    models.py
    predictor.py
    uncertainty.py
```

建议接入方式：

1. `executor.evaluate(sequence)` 先照常拿结构指标；
2. `surrogate.predict(sequence, structure_metrics)` 输出：
   - `predicted_fluorescence`
   - `prediction_std`（如果用了 ensemble）
   - `model_version`
3. 最终用配置决定评分方式：
   - `structure-only`
   - `surrogate-only`
   - `hybrid`

推荐的 hybrid 公式：

```text
hybrid_score =
    0.70 * surrogate_fluorescence_norm +
    0.30 * structure_score
```

原因：

- surrogate 更接近真实实验目标；
- structure score 仍然能防止模型把明显不折叠的序列排到前面。

### 4.8 第二层建议增加的配置项

建议在 `settings.py` 增加：

- `PROTEIN_AGENT_SCORING_BACKEND=surrogate`
- `PROTEIN_AGENT_SURROGATE_MODEL_PATH=...`
- `PROTEIN_AGENT_SURROGATE_MODEL_TYPE=xgboost`
- `PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES=true`
- `PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE=5`
- `PROTEIN_AGENT_SURROGATE_SCORE_MODE=hybrid`

### 4.9 第二层的验收标准

第二层完成后，至少要达到：

1. 可以离线训练并保存 surrogate model；
2. 线上推理能读取模型并返回 `predicted_fluorescence`；
3. memory 中能记录 `model_version` 和 `prediction_std`；
4. 在离线验证里，surrogate 的排序指标优于第一层纯结构代理；
5. 即使 surrogate 暂时加载失败，系统也能回退到第一层结构评分，不影响主流程。

---

## 5. 第三层：主动学习闭环

这一层才是 Agent 系统真正能持续变强的部分，但它必须建立在前两层稳定的前提上。

### 5.1 目标

把系统从“会打分”升级为“会主动决定下一批最值得实验的候选”。

闭环如下：

```text
设计候选 → 代理模型打分 → 不确定性评估 → 选择 top-k → 湿实验验证
   ↑                                                        ↓
   └────────────── 实测结果回写 memory，重新训练 surrogate ──────────────┘
```

### 5.2 先做一个最小可行闭环

不要一开始就上很复杂的贝叶斯优化系统，先做 MVP：

1. 模型输出预测均值 `μ`；
2. ensemble 输出不确定性 `σ`；
3. 用一个简单采集函数选实验样本；
4. 导入实验结果后自动增量训练。

### 5.3 为什么 uncertainty 很重要

如果只选分数最高的 top-k，你会不断采样“模型最自信的一小块区域”，容易错过真正有潜力但模型还没见过的序列。

所以主动学习里最关键的不是只有 `score`，而是：

- 预测均值 `μ`
- 预测不确定性 `σ`

推荐的第一版采集函数：

```text
acquisition = μ + λσ
```

其中：

- `μ` 高：倾向 exploitation；
- `σ` 高：倾向 exploration；
- `λ` 控制探索强度。

### 5.4 不确定性估计怎么做

你的思路是对的，优先选择：

#### 方案 A：Ensemble

最推荐作为第一版。

做法：

- 训练 5 个不同随机种子的 XGBoost 或 MLP；
- 推理时输出均值和标准差；
- 标准差作为 epistemic uncertainty 近似。

优点：

- 简单；
- 工程上稳定；
- 容易和现有服务整合。

#### 方案 B：MC Dropout

适合你后面如果改用 MLP 主模型时补上。

但第一版没有 ensemble 直观，建议放在第二阶段。

### 5.5 实验结果怎么回写

建议新增一个明确的数据入口，而不是手动改代码。

可以是：

- 一个 CSV 导入脚本；
- 或一个 API endpoint，例如 `/ingest_experiment_results`。

每条实验记录至少包含：

- `sequence`
- `measured_fluorescence`
- `assay_batch`
- `measurement_date`
- `instrument`
- `temperature`
- `notes`

然后写入两处：

1. `ExperimentMemory`：用于在线回顾；
2. 持久化数据集文件：用于下次训练。

### 5.6 memory 结构需要升级

当前 `ExperimentMemory` 只适合保存一轮设计中的候选记录。

进入第三层后，建议每条记录分成三类字段：

#### 设计字段

- `sequence`
- `mutation_history`
- `iteration`

#### 预测字段

- `structure_score`
- `surrogate_score`
- `predicted_fluorescence`
- `prediction_std`
- `acquisition_score`
- `model_version`

#### 实验字段

- `measured_fluorescence`
- `experimental_rank`
- `assay_batch`
- `wetlab_status`

这样你后面才能做真正的 retrospective analysis。

### 5.7 top-k 选择不要只看分数，还要看多样性

这是主动学习里第二个容易被忽略的问题。

如果 top-k 全部只差 1 个位点，湿实验资源会被浪费在一个很窄的局部区域。

建议在 `μ + λσ` 之外再加一个 diversity filter：

- 候选之间最小 Hamming 距离约束；
- 或 embedding 空间聚类后每簇取一个；
- 或同一父本 lineage 不超过固定数量。

### 5.8 什么时候引入 BoTorch

你的想法没问题，但我建议把 BoTorch 放在第三层后半段，而不是第三层一开始。

原因：

- 你先得有稳定的 surrogate 和 uncertainty；
- 先用 `UCB = μ + λσ` 就能跑起来；
- 之后再把 latent embedding 空间上的采集函数替换成更正式的贝叶斯优化。

推荐顺序：

1. 先 ensemble + UCB；
2. 再加 diversity filtering；
3. 最后再接 BoTorch。

### 5.9 第三层的验收标准

第三层做完后，至少应该具备：

1. 能导入湿实验结果；
2. 能把实验结果追加进训练集；
3. 能自动重训 surrogate 并生成新模型版本；
4. 能基于 `μ` 和 `σ` 计算采集分数；
5. 能输出一批兼顾高分与多样性的待实验候选。

---

## 6. 推荐的工程拆分方式

为了避免后续代码越堆越乱，建议按下面的模块边界推进。

### 6.1 结构评分层

建议涉及这些文件：

- `protein_agent/esm3_integration/bridge.py`
- `protein_agent/esm3_server/server.py`
- `protein_agent/tools/esm3_structure.py`
- `protein_agent/tools/protein_score.py`
- `protein_agent/agent/executor.py`
- `protein_agent/memory/experiment_memory.py`

主要动作：

- 统一结构指标 schema；
- 重写 score 逻辑；
- 记录 score breakdown。

### 6.2 监督代理层

建议新增：

```text
protein_agent/
  surrogate/
    dataset.py
    features.py
    train.py
    predictor.py
    uncertainty.py
scripts/
  prepare_gfp_dataset.py
  extract_gfp_embeddings.py
  train_gfp_surrogate.py
```

主要动作：

- 读入和清洗数据；
- 提取 embedding；
- 训练/保存/加载模型；
- 暴露统一预测接口。

### 6.3 主动学习层

建议新增：

```text
protein_agent/
  active_learning/
    acquisition.py
    selection.py
    retrain.py
    ingest.py
```

主要动作：

- 采集函数；
- diversity 过滤；
- 实验结果导入；
- 模型重训编排。

---

## 7. 推荐的实施顺序

如果你要实际排开发任务，我建议按下面顺序开工。

### 第 1 周：先把第一层做完

1. 扩展结构输出 schema；
2. 重写 `protein_score.py`；
3. 加上 `SYG` 强约束；
4. 把评分细节写入 memory；
5. 做 20~50 个候选的离线 sanity check。

### 第 2 周：离线做监督代理 baseline

1. 清洗 `Sarkisyan 2016`；
2. 建立训练/验证/测试切分；
3. 提取 ESM3 embedding；
4. 先训一个 XGBoost baseline；
5. 比较它和第一层 structure score 的排序能力。

### 第 3 周：把 surrogate 接到线上

1. 新增预测器加载逻辑；
2. 支持 `structure / surrogate / hybrid` 三种评分模式；
3. 输出 `prediction_std` 和 `model_version`；
4. 做回退机制。

### 第 4 周以后：开始主动学习 MVP

1. 用 ensemble 估 uncertainty；
2. 用 `μ + λσ` 选样；
3. 加实验导入入口；
4. 加持久化训练集和重训脚本；
5. 观察每轮 top-k 的实验命中率是否提升。

---

## 8. 一些容易踩坑的地方

### 8.1 不要把“结构置信度”误当成“功能置信度”

高 `pLDDT` 不代表高荧光。

它只能说明：

- 这条序列更可能折成稳定结构；

但不能保证：

- 色团成熟正常；
- 光谱性质更好；
- 表达量更高。

这就是为什么第一层只是过渡，第二层必须用实验数据来纠偏。

### 8.2 motif 约束不能只写在 prompt

因为 prompt 约束不是强约束，模型很容易在探索时把关键位点一起改坏。

### 8.3 数据切分不严会导致 surrogate 指标虚高

如果测试集和训练集只差一个突变位点，结果会非常乐观，但上线设计时不一定有用。

### 8.4 Rosetta 不适合一开始放主路径

否则每轮迭代的吞吐会掉很多，系统响应时间会很差。

### 8.5 第三层一定要做版本管理

至少记录：

- 数据版本；
- surrogate 模型版本；
- scoring formula 版本；
- 实验批次版本。

否则几轮之后你就很难解释为什么系统行为变了。

---

## 9. 如果以后还要设计其他蛋白，建议现在就补上的通用化改造

你这份方案已经能很好地支撑 **GFP-first** 的落地，但如果你明确知道后面还要做其他蛋白，那么建议现在就把下面这些“架构层”的东西补进去。否则后面很容易出现一种情况：GFP 方案能跑，但一换目标蛋白就要大改 API、memory、scoring 和 surrogate。

### 9.1 先统一 reference contract，不要让坐标体系漂移

这是优先级最高的补强点。

当前仓库里其实已经出现了两套 GFP 参考体系：

- 一套是文档里这份计划使用的 `238 aa / 65-67 / full-length scaffold`
- 另一套是后续 Phase 2 和硬约束文档里使用的 `236 aa / 63-65 / mature avGFP`

这件事如果在 GFP 阶段都不彻底统一，后面迁移到其他蛋白会更麻烦，因为别的目标蛋白也常常会遇到：

- 信号肽切除前后编号不同；
- pro-peptide 和 mature form 编号不同；
- 文献编号、PDB 编号、实验构建编号不一致；
- N 端或 C 端带 tag，导致 mutation token 不可直接映射。

建议把“参考坐标 contract”明确成一等公民，至少固定以下字段：

- `reference_id`
- `reference_name`
- `reference_sequence`
- `reference_length`
- `coordinate_system`
- `mature_offset`
- `reference_hash`
- `constraint_positions`

然后要求以下所有模块都只认这份 canonical contract：

- 数据清洗脚本
- 评分模块
- 约束检查
- memory 落盘
- 主动学习数据集构建

这样以后无论是 GFP、酶、抗体片段还是 binder，坐标体系都不会散掉。

### 9.2 把 “是不是 GFP” 的字符串判断，升级成 TargetProfile

现在仓库里多处逻辑本质上还是：

- task 里包含 `gfp`
- 就启用 GFP 约束
- 就走 GFP surrogate

这对当前阶段够用，但它不是一个可扩展架构。

建议新增一个显式的 `TargetProfile` 概念，替代散落在代码里的 `gfp_*` 特判。一个最小 profile 可以长这样：

```yaml
target_id: gfp
target_type: soluble_monomer
reference:
  sequence: ...
  coordinate_system: mature_avGFP_236
objectives:
  primary_assay: fluorescence
  direction: maximize
constraints:
  fixed_residues:
    - {position: 63, residue: S}
    - {position: 64, residue: Y}
    - {position: 65, residue: G}
  allowed_length_range: [236, 236]
structure_scoring:
  enabled_metrics: [mean_plddt, ptm]
surrogate:
  task_type: regression
  model_family: xgboost_ensemble
```

建议后面把这些位置都改成“吃 profile”而不是“猜是不是 GFP”：

- `protein_agent/api/main.py`
- `protein_agent/agent/workflow.py`
- `protein_agent/tools/protein_score.py`
- `protein_agent/agent/executor.py`
- `protein_agent/surrogate/*`

这样未来新增一个目标蛋白时，优先是“新建一个 profile”，而不是“复制一份 GFP 代码再手改”。

### 9.3 把硬约束系统做成声明式，而不是只服务于色团 motif

当前你已经在 GFP 上验证了一个很重要的工程原则：**关键位点不能只写在 prompt 里**。

下一步建议把它再抽象一层，让约束系统不再默认自己服务于 `SYG`，而是支持更通用的 constraint types，例如：

- 固定残基
- motif 保留
- 长度范围
- 禁止位点
- 允许突变位点白名单
- 二硫键配对
- 催化位点保留
- 接口位点保留
- 避免引入 glycosylation / cleavage 等风险 motif

形式上最好是声明式 schema，而不是继续写成 `require_gfp_chromophore` 这种单目标布尔量。因为以后你做的很多蛋白根本没有 chromophore，但同样会有“必须不动”的功能核心。

### 9.4 把 assay schema 标准化，不要把 surrogate 默认等同于“荧光回归”

这份方案第二层现在默认的是：

- 输入序列
- 输出荧光强度

这对于 GFP 是对的，但一旦换到其他蛋白，标签可能变成：

- 酶活
- 热稳定性
- 表达量
- 结合亲和力
- 抑制率
- 存活率
- 分类标签而不是回归值

所以建议你现在就把 dataset / surrogate 的标签 schema 标准化，至少统一这些字段：

- `assay_name`
- `assay_type`
- `label_name`
- `label_value`
- `label_unit`
- `label_transform`
- `optimization_direction`
- `batch_id`
- `condition`
- `replicate_count`
- `label_std`

这样后面 surrogate 才不会在接口层被绑死成 `predicted_fluorescence` 这一种输出。

### 9.5 把 surrogate 抽象成统一接口，允许 target-specific feature plugin

现在的命名和实现还是明显偏 GFP：

- `GFPFluorescencePredictor`
- `GFPDatasetConfig`
- `FeatureConfig` 默认引用 GFP scaffold

建议后续拆成两层：

1. 通用层：
   - `SurrogatePredictor`
   - `DatasetConfig`
   - `FeatureExtractor`
2. 目标层：
   - `GFPProfileFeaturePlugin`
   - `EnzymeActiveSiteFeaturePlugin`
   - `BinderInterfaceFeaturePlugin`

这样你就可以把“序列 embedding + 通用结构特征 + 目标特有规则特征”分开管理。

对于其他蛋白，真正会变化的往往不是整个训练框架，而是：

- 参考序列
- 对齐方式
- 关键位点特征
- 结构打分分量
- 标签定义

### 9.6 把离群检测、校准和探索策略提前设计进去

GFP 有公开 DMS 数据，做 surrogate 相对舒服；但以后很多目标蛋白可能只有几十到几百个样本。

这种场景下，比“预测均值”更重要的是：

- 这个点是不是分布外；
- 这个不确定性是不是校准过；
- 这个 top-k 是不是全挤在一个局部序列邻域里。

所以建议把下面这些字段提前纳入 memory 和模型产物：

- `prediction_std`
- `train_distance`
- `novelty_score`
- `calibration_version`
- `acquisition_score`

这样后面你做 active learning 的时候，才能自然切到：

- exploit：高预测值
- explore：高不确定性
- diversify：高新颖度 / 低聚类密度

### 9.7 给不同蛋白预留多目标优化接口

GFP 相对单纯，因为你现在主目标很明确，就是亮度。

但其他蛋白常见的真实目标是：

- 活性更高
- 稳定性更高
- 表达更好
- 聚集更少
- 特异性更强
- 脱靶更低

这时再把所有东西硬压成一个单值 `score` 往往会过早丢信息。

建议你至少在 schema 层支持：

- `primary_objective`
- `secondary_objectives`
- `hard_constraints`
- `soft_objective_weights`

即便线上排序最后还是单值，也建议在 memory 里把多目标分量完整保留。这样以后要切 Pareto ranking 或 constrained optimization 时，不需要回头重做存储层。

### 9.8 做一个统一的 retrospective benchmark harness

如果后面真要做多个蛋白，强烈建议不要每个目标都“训练一次看着还行就上线”。

更稳妥的方式是统一做一个 retrospective harness，用历史数据离线比较：

- random selection
- greedy top-k
- uncertainty sampling
- diversity-aware top-k
- hybrid acquisition

每个目标至少固定输出：

- split 方案
- ranking 指标
- top-k hit rate
- calibration 指标
- novelty 分布
- active-learning 模拟曲线

这会让你后面做新蛋白时非常快，因为你不需要重新发明一套评估方法。

### 9.9 memory 和模型版本字段再往前走一步

你文档里已经强调版本管理，这个方向是对的，但如果以后会跨蛋白复用，建议版本信息再细一层：

- `target_id`
- `target_profile_version`
- `reference_id`
- `reference_hash`
- `constraint_profile_version`
- `dataset_version`
- `split_version`
- `feature_version`
- `model_version`
- `calibration_version`
- `scoring_formula_version`

这样你将来看到一条历史记录时，能知道它到底是：

- 哪个蛋白；
- 用哪套参考坐标；
- 哪个 surrogate；
- 哪个 acquisition 策略；
- 哪套约束规则。

### 9.10 建议的优先级

如果你不想一下子做太多，我建议按这个顺序补：

1. **先补**：统一 reference contract，消除 `238/65` 和 `236/63` 两套 GFP 坐标并存的问题。
2. **接着补**：引入 `TargetProfile`，把 `gfp` 字符串判断从 API / workflow / scoring / surrogate 中拿掉。
3. **然后补**：把约束、assay schema、surrogate 接口都改成 protein-agnostic。
4. **最后补**：再上多目标优化、OOD、校准和更复杂的 acquisition。

---

## 10. 最后给你的明确建议

如果只看“现在最该做什么”，建议是：

### 立刻做

1. 先统一 GFP 参考坐标，只保留一套 canonical contract；
2. 把 `protein_score.py` 从启发式比例打分改成 `mean_pLDDT + pTM + SYG约束`；
3. 把 `bridge.py` 的结构输出变成稳定 schema；
4. 把 `score_breakdown` 和 motif 检查结果写入 memory。

### 紧接着做

5. 把 `gfp` 字符串判断抽成 `TargetProfile`；
6. 离线整理 `Sarkisyan 2016` 数据；
7. 用 ESM3 embedding 训一个 XGBoost surrogate baseline；
8. 让线上支持 `hybrid score`。

### 最后做

9. 把 surrogate 输出改成 assay-agnostic schema；
10. 加 ensemble uncertainty；
11. 加实验导入接口；
12. 再考虑 BoTorch 和更复杂的采集函数。

一句话总结：**先把当前启发式 score 升级成结构代理，再用 GFP 公共数据把它升级成实验驱动 surrogate，最后再闭环主动学习。** 这是最稳、最科学、也最符合你当前仓库状态的路线。
