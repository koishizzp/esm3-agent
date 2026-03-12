# ESM3-Agent：一个面向自治蛋白设计的多模态代理系统

## 摘要

本文以系统论文的写法，对仓库 `esm3-agent` 进行结构化说明。该系统的核心目标，是将 ESM3 的序列生成、突变、结构预测、逆折叠和功能条件化生成能力，组织为一个可通过 API 调用、可进行多轮搜索、可集成约束、可接入监督代理模型、并可进一步扩展到主动学习闭环的自治蛋白设计平台。当前实现采用分层架构：底层为本地或 HTTP 方式接入的 ESM3 runtime，中层为工具执行与实验循环引擎，上层为面向自然语言和多模态输入的 FastAPI 服务。系统已经具备 GFP 定向优化、结构代理评分、GFP 监督 surrogate、硬约束、实验记忆落盘以及主动学习数据闭环的最小能力，但仍保留若干明显的目标蛋白特化痕迹，例如 GFP 任务识别、GFP 参考坐标配置以及 GFP surrogate 命名。本文重点说明该仓库的设计动机、模块分工、核心算法流程、工程落点、当前能力边界与后续演进方向。

## 关键词

蛋白设计，ESM3，自治代理，主动学习，结构代理评分，监督 surrogate，多模态工作流

## 1. 引言

大模型驱动的蛋白设计系统通常面临两个工程难题。第一，底层模型能力本身是碎片化的，不同操作分别对应序列生成、结构预测、逆折叠、功能条件化生成等接口，很难直接构成稳定的设计流程。第二，真实设计任务不是单次推理，而是一个包含候选提出、约束施加、评分排序、多轮突变、结果记录、模型更新乃至实验回写的闭环。

`esm3-agent` 的设计目标正是解决这一断层。它并不把 ESM3 当作一个单点 API，而是把 ESM3 作为底层推理内核，再由代理系统完成以下上层组织：

1. 将自然语言任务映射为可执行设计计划。
2. 将序列、结构、功能与硬约束整合为同一请求上下文。
3. 通过生成、评估、选择、突变的循环形成自动化定向进化式优化。
4. 用结构代理分和监督 surrogate 作为在线排序器。
5. 用实验记忆与主动学习脚本支持模型版本化迭代。

从研究类型上看，这个仓库更接近一个系统原型与工程平台，而不是已经完成严格实验验证的“算法论文”。因此，本文关注的是“系统如何工作”与“当前实现到了哪一步”，而不是夸大其科学结论。

## 2. 系统目标与问题定义

该系统当前聚焦的代表任务是 GFP 优化，但其抽象问题可表述为：

给定一个蛋白工程任务描述，以及可选的参考序列、结构、功能关键词、功能注释、长度目标和固定位点约束，系统需要在限定轮数内自动产生候选序列，调用底层模型进行结构或功能相关评估，对候选做排序与筛选，并在需要时将设计记录持久化，以支持后续实验导入与 surrogate 重训练。

相较于纯生成系统，该仓库额外强调以下三点：

1. 约束不是只写在 prompt 中，而是进入显式数据结构和评分逻辑。
2. 评分不是单一启发式，而是允许从结构代理走向监督 surrogate，再走向主动学习。
3. 运行结果不是一次性返回，而是作为可回放 artifact 落盘。

## 3. 总体架构

系统可以概括为四层：

```text
用户/API 请求
    ↓
FastAPI 编排层
    ↓
Planner + Workflow + Executor
    ↓
ESM3 Tools + Protein Scoring + Surrogate
    ↓
Local/HTTP ESM3 Runtime + Active Learning Storage
```

### 3.1 接口编排层

最上层由 `protein_agent/api/main.py` 提供统一入口。当前主要暴露：

- `POST /design_protein`
- `POST /inverse_fold`
- `POST /generate_with_function`
- `POST /chat_reasoning`
- `GET /health`
- `GET /ui/status`

这一层的职责不是做具体蛋白设计，而是完成请求标准化、上下文融合、约束解析、工作流分发、artifact 落盘以及结果摘要。

### 3.2 工作流与执行层

中层由三个核心对象协作完成：

- `LLMPlanner`
- `ExperimentLoopEngine`
- `ToolExecutor`

其中 `LLMPlanner` 负责将自然语言任务转成结构化 plan；`ExperimentLoopEngine` 负责多轮生成、评估、选择、再生成；`ToolExecutor` 负责把 plan 中的“能力动作”映射到具体工具与评分模块。

### 3.3 模型与评分层

模型与评分层包含两类能力：

1. ESM3 原生能力：
   - 序列生成
   - 突变生成
   - 结构预测
   - 逆折叠
   - 功能条件化生成
2. 仓库自建评估能力：
   - 结构代理评分
   - GFP 监督 surrogate
   - hybrid 评分融合

### 3.4 持久化与主动学习层

最底层除 ESM3 runtime 外，还包括：

- `ExperimentMemory`
- JSON / JSONL artifact 存储
- active-learning 目录布局
- wet-lab 导入与重训练脚本

这使系统不再是“调用后即丢失上下文”的黑盒，而是具备最小实验平台属性。

## 4. 底层 ESM3 接入机制

### 4.1 独立 ESM3 服务

`protein_agent/esm3_server/server.py` 实现了本地 FastAPI 模型服务。其核心特点是：

1. 在启动时完成运行时路径配置。
2. 根据环境变量选择设备，例如 `cuda` 或 `cpu`。
3. 使用桥接层直接加载 ESM3 模型。
4. 通过独立 HTTP 端点暴露生成、突变、结构预测、逆折叠与功能条件化生成能力。

这样的好处是，上层 Agent 不需要直接关心 ESM3 的模型初始化与运行环境，只需通过统一 client 调用。

### 4.2 本地/HTTP 双形态桥接

从配置设计看，仓库支持将 ESM3 视作本地模型能力或 HTTP 服务能力。工程上，这意味着：

- 本地单机部署时，可以直接加载本机权重。
- 服务化部署时，可以把 ESM3 runtime 与 Agent API 分开。

这种解耦对实际运维很重要，因为 ESM3 的模型资源管理与上层工作流逻辑并不是同一类问题。

## 5. 规划、执行与搜索机制

### 5.1 规划器

`protein_agent/agent/planner.py` 中的 `LLMPlanner` 采用“LLM 可用则调用，否则回退”的策略。

其行为分两种：

1. 若配置了 OpenAI 兼容客户端，则尝试让模型生成 JSON 计划。
2. 若客户端不可用或输出不可解析，则回退到确定性模板。

这种设计反映出一个重要工程取向：系统的可运行性优先于“必须依赖 LLM 规划”。

### 5.2 多轮实验循环

`ExperimentLoopEngine` 定义了核心搜索过程：

1. 初始化种群。
2. 对每个候选执行结构预测和评分。
3. 过滤无效候选。
4. 保留 elite。
5. 以 parent pool 为基础产生下一代突变体。
6. 若种群不足，则再生成新序列填充。
7. 达到最大轮数或连续若干轮无提升时停止。

这使系统具备了典型 evolutionary search 的外形，而不是简单的 greedy top-1 修补。

### 5.3 初始化策略

初始化种群并非只靠单一路径，而是综合：

- 用户显式给定的参考序列
- 由结构输入触发的逆折叠候选
- 由功能关键词或注释触发的功能条件化候选
- 不足时再用纯生成补齐

这一机制使 `/design_protein` 实际上是一个多模态候选启动器，而不只是文本接口。

## 6. 约束建模与候选合法性控制

### 6.1 显式约束对象

`protein_agent/constraints.py` 提供了 `SequenceConstraints` 抽象，当前支持：

- 参考长度
- 固定残基

它可以在候选进入评分前进行投影，也可以在评分阶段生成违反约束的报告。

### 6.2 GFP 硬约束

当前系统对 GFP 任务还带有明显特化：

- 若任务文本包含 `gfp`，系统会自动加入 chromophore `SYG` 约束。
- GFP 相关长度、发色团起点和 motif 都来自配置项。

这说明系统已经具备“显式硬约束优于 prompt 约束”的正确方向，但也说明仓库仍未完全抽象出目标蛋白无关的 `TargetProfile` 层。

## 7. 在线评分机制

### 7.1 结构代理评分

`protein_agent/tools/protein_score.py` 当前承担在线结构代理评分。它会从结构结果中提取：

- `mean_plddt`
- `ptm`
- `iptm`
- `confidence`

并结合约束信息构造：

- `score`
- `metrics`
- `score_breakdown`
- `valid_candidate`

对于 GFP，还会进一步考虑：

- motif 完整性
- 长度偏差
- 固定位点违反情况

这使评分结果同时具备排序性和审计性。

### 7.2 监督 surrogate 与 hybrid 评分

`protein_agent/agent/executor.py` 将结构代理评分与监督 surrogate 连接在一起。当前支持三种模式：

- `structure`
- `surrogate`
- `hybrid`

若 surrogate 可用，则当前 hybrid 公式实质上为：

```text
final_score = 0.70 * surrogate_score + 0.30 * structure_component - penalties
```

其中惩罚项主要来自 motif 与长度约束。

如果 surrogate 不可用，系统会自动回退到结构评分并记录 `structure_fallback`，从而避免在线流程因模型加载失败而整体崩溃。

## 8. GFP 监督 surrogate 的实现位置与作用

### 8.1 预测器

`protein_agent/surrogate/predictor.py` 中的 `GFPFluorescencePredictor` 当前是一个 GFP 特化在线预测器。它会：

1. 从模型目录加载 ensemble bundle。
2. 使用特征提取器构造输入特征。
3. 输出：
   - `predicted_fluorescence`
   - `prediction_std`
   - `surrogate_score`
   - `model_version`

其中 `prediction_std` 提供了最小形式的不确定性信号，为主动学习提供基础。

### 8.2 工程意义

监督 surrogate 的意义，不在于直接代替实验真值，而在于：

1. 比纯结构评分更贴近目标表型。
2. 为主动学习中的候选筛选提供可重复的打分后端。
3. 使系统能够从“结构驱动筛选”过渡到“实验数据驱动筛选”。

但必须强调：当前命名、标签定义和特征工程都仍偏 GFP，尚未完全 protein-agnostic。

## 9. 记忆系统与主动学习闭环

### 9.1 实验记忆

`protein_agent/memory/experiment_memory.py` 中的 `ExperimentMemory` 会记录每个候选的：

- 序列
- 突变历史
- 评分
- 轮次
- 结构数据
- 元数据

并支持：

- `top_k`
- `best`
- JSON 序列化与反序列化

### 9.2 Artifact 存储

`protein_agent/memory/storage.py` 负责：

- JSON / JSONL 读写
- active-learning 目录结构创建
- 运行结果文件命名

典型目录为：

```text
data/active_learning/
  runs/
  batches/
  wetlab/
  datasets/
  active_model.json
```

### 9.3 当前主动学习能力

仓库已经包含最小主动学习所需的脚本链路：

- 导出 batch
- 导入 wet-lab 结果
- 构建 merged dataset
- 重训 surrogate
- promotion 新模型

从系统角度看，这意味着仓库已经不只是“在线设计工具”，而是一个具备最小闭环能力的原型平台。

## 10. API 语义与多模态输入设计

`/design_protein` 是当前最核心的统一接口。它允许用户在同一请求中组合：

- 文本任务
- 参考序列
- 结构路径或 PDB 文本
- 功能关键词
- 功能注释
- 目标长度
- 固定位点

该接口的关键价值，不只是“参数多”，而是这些输入会被统一转化为：

1. `multimodal_context`
2. `sequence_constraints`
3. `initial_sequences`
4. `plan`

然后进入同一个工作流引擎执行。换言之，这个接口对应的是多模态设计问题，而不是多个独立 API 的拼接。

## 11. 当前最有代表性的任务形态：GFP 优化

仓库现阶段最成熟的内置任务是 GFP。对应实现包括：

- `protein_agent/workflows/gfp_optimizer.py`
- GFP scaffold
- GFP chromophore 约束
- GFP surrogate
- GFP active-learning 数据路径与脚本

这种以单一代表任务为牵引的做法，在系统早期是合理的，因为它提供了：

1. 可操作的 benchmark 场景。
2. 结构代理与实验 surrogate 的结合样例。
3. 主动学习闭环的落地对象。

但从系统演化角度，它也带来了当前最明显的限制：很多逻辑仍通过“是否包含 gfp”来触发。

## 12. 当前系统的能力边界

### 12.1 已具备的能力

当前仓库已经明确具备：

1. 基于 FastAPI 的统一蛋白设计接口。
2. 本地或 HTTP 方式接入真实 ESM3。
3. 生成、突变、结构预测、逆折叠、功能条件化生成。
4. 结构代理评分与 GFP 监督 surrogate。
5. 固定位点和 GFP chromophore 硬约束。
6. 多轮 evolutionary-style 搜索。
7. 运行结果 artifact 落盘。
8. 主动学习最小数据闭环。

### 12.2 尚未完成的抽象

系统目前尚未完全完成：

1. 面向任意目标蛋白的 `TargetProfile` 抽象。
2. assay-agnostic 的 surrogate 输出接口。
3. 多目标优化接口。
4. 更严格的 OOD 检测与不确定性校准。
5. 与真实湿实验平台的全自动联动。

### 12.3 需要审慎理解的点

当前仓库虽然具备 surrogate 和 active learning 组件，但这不意味着它已经自动具备了可靠的科学发现能力。至少以下几点仍需谨慎：

- 高 `pLDDT` 不等于高功能。
- 高 surrogate score 不等于实验必然成功。
- GFP 的成功路径不能直接视作其他蛋白的即插即用方案。
- 目前很多默认值和命名仍带 GFP 特征。

## 13. 工程亮点与设计取舍

从工程视角看，这个仓库最值得肯定的地方有三点。

第一，系统把“底层模型能力”和“上层实验流程”清晰分层。  
第二，系统把 prompt 约束逐渐替换为显式 schema、显式 score 和显式 artifact。  
第三，系统保留了从纯在线推理到主动学习平台的自然升级路径。

与此同时，也有三个非常明确的技术债。

第一，目标蛋白抽象仍不足。  
第二，GFP 路线中的 reference 与坐标体系曾出现历史漂移。  
第三，surrogate 层的命名和数据 schema 还未完全泛化。

## 14. 后续演进方向

如果把这个仓库看作一篇系统论文的“future work”，最自然的下一步是：

1. 引入 `TargetProfile`，把 GFP 特判收敛为 profile 驱动。
2. 将 surrogate、assay、constraint schema 做成 protein-agnostic。
3. 引入 novelty、distance、calibration 等主动学习元信息。
4. 增加多目标排序与 constrained optimization。
5. 对不同蛋白目标建立统一 retrospective benchmark harness。

这些方向并不是重写系统，而是在现有架构上继续抽象和稳定化。

## 15. 结论

`esm3-agent` 可以被理解为一个以 ESM3 为底层推理内核、以代理工作流为组织形式、以 GFP 为当前主验证对象的自治蛋白设计系统。其真正价值不只是“能生成序列”，而在于它把多模态输入、约束、结构代理评分、监督 surrogate、实验记忆和主动学习脚本组织成了一个可落盘、可回放、可扩展的工程平台。

从成熟度上看，该仓库已经越过了“单次 demo”阶段，进入了“系统原型可演进”的阶段；但从抽象完备性上看，它仍处于从 `GFP-first` 迈向 `protein-agnostic platform` 的中间位置。正因为如此，这个仓库最适合被理解为一篇系统论文对应的代码原型：核心架构已成型，代表任务已打通，下一阶段重点不再是堆更多接口，而是提高抽象层次、减少目标蛋白耦合，并建立更严格的实验与评估规范。

