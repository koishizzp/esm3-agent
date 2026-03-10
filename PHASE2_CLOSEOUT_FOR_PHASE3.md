# Phase 2 收尾到 Phase 3

当你已经得到一个可用的 surrogate model，并准备进入 active-learning 循环时，可以使用这份文档。

本指南默认你将使用：

- 模型目录：
  `/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1_randomsplit`
- mature avGFP 参考序列：
  `236 aa`
- 发色团：
  位于 `63-65` 位点的 `SYG`


## 1. 什么情况下可以算 “Phase 2 已完成”

如果以下条件都成立，就可以认为 Phase 2 已完成：

- `data/gfp/processed/dataset_summary.json` 内容看起来正常
- `data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json` 显示所有序列都已成功完成 embedding
- `models/gfp_surrogate/xgb_ensemble_v1_randomsplit/training_report.json` 中的指标看起来正常
- 模型目录中包含：
  - `model_0.joblib` ... `model_4.joblib`
  - `feature_config.json`
  - `metadata.json`
  - `training_report.json`


## 2. 建议保留的输出文件

建议保留以下内容：

- `data/gfp/raw/amino_acid_genotypes_to_brightness.tsv`
- `data/gfp/raw/avGFP_reference_mature.fa`
- `data/gfp/processed/dataset_summary.json`
- `data/gfp/embeddings/esm3_mean_v1/offline_run/run_summary.json`
- `models/gfp_surrogate/xgb_ensemble_v1_randomsplit/`

以下这些基于错误前提产生的早期运行结果，不需要保留：

- DNA reference FASTA
- 之前那个不匹配的 `238 aa` 全长参考序列


## 3. 把 `.env` 更新为你要在线使用的模型

编辑 `.env`，确认下面这些变量已经设置：

```bash
PROTEIN_AGENT_SCORING_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_MODEL_PATH=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction/esm3-agent/models/gfp_surrogate/xgb_ensemble_v1_randomsplit
PROTEIN_AGENT_SURROGATE_MODEL_TYPE=xgboost
PROTEIN_AGENT_SURROGATE_ENSEMBLE_SIZE=5
PROTEIN_AGENT_SURROGATE_FEATURE_BACKEND=hybrid
PROTEIN_AGENT_SURROGATE_USE_STRUCTURE_FEATURES=false

PROTEIN_AGENT_REQUIRE_GFP_CHROMOPHORE=true
PROTEIN_AGENT_GFP_REFERENCE_LENGTH=236
PROTEIN_AGENT_GFP_CHROMOPHORE_START=63
PROTEIN_AGENT_GFP_CHROMOPHORE_MOTIF=SYG
```

可用下面的命令检查：

```bash
grep -E "PROTEIN_AGENT_SCORING_BACKEND|PROTEIN_AGENT_SURROGATE_|PROTEIN_AGENT_GFP_REFERENCE_LENGTH|PROTEIN_AGENT_GFP_CHROMOPHORE_START|PROTEIN_AGENT_GFP_CHROMOPHORE_MOTIF" .env
```


## 4. 进入 Phase 3 之前的重要提醒

当前代码库里，GFP 默认 seed 的行为很可能仍然存在不匹配问题：

- 在线工作流的默认 seed 来自 `protein_agent/gfp.py`
- 这个默认 scaffold 可能仍然是旧的全长 GFP 序列
- 你训练出来的 surrogate 基于 mature avGFP（`236 aa`，发色团起始位点是 `63`）

这意味着：

- 如果你启动 GFP 工作流时没有显式传入 `sequence`，优化器可能会从错误的 scaffold 开始
- 这样一来，打分和 surrogate prediction 就会和设计时使用的 seed 不一致


## 5. 在修默认值之前，最快也最安全的规则

在你明确把代码默认值对齐之前，Phase 3 的请求里始终传入 mature avGFP 的 seed sequence。

请使用下面这条 mature avGFP 序列：

```text
KGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK
```

如果你省略了 `sequence`，不要假设工作流会自动使用 mature 版本。


## 6. 修改 `.env` 后重启服务

如果你使用仓库自带脚本：

```bash
./stop_all.sh
./start_all.sh
```

如果你平时是分开启动服务的，也可以分别重启 ESM3 server 和 Agent API。

然后执行检查：

```bash
./status_all.sh
```


## 7. 最小在线冒烟测试

在开始 Phase 3 之前，先对 `/design_protein` 做一次在线冒烟测试。

示例：

```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H "Content-Type: application/json" \
  -d '{
    "task": "Design an improved GFP and iteratively optimize it",
    "sequence": "KGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTLKFICTTGKLPVPWPTLVTTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDGNYKTRAEVKFEGDTLVNRIELKGIDFKEDGNILGHKLEYNYNSHNVYIMADKQKNGIKVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQSALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK",
    "max_iterations": 1,
    "candidates_per_round": 2,
    "patience": 1
  }'
```

你需要在返回结果里确认以下几点：

- 请求成功执行
- `scoring.backend` 是 `hybrid`
- best-candidate 的 metadata 中显示：
  - `score_mode = hybrid`
  - `surrogate_available = true`
  - `model_version = xgb_ensemble_v1_randomsplit`


## 8. 即使模型已经训练完，这些仍然属于 Phase 2 的收尾工作

真正的 closeout 检查项如下：

1. `.env` 中的模型路径指向了正确的模型版本。
2. `.env` 中的 GFP 约束配置与 mature avGFP 的坐标一致。
3. 在线 API 的确能够加载 surrogate model。
4. 实际调用 `/design_protein` 时返回的是 `hybrid` scoring，而不是退回到 structure fallback。
5. 你已经决定好以下二选一中的哪一种：
   - 继续在请求里显式传入 `sequence`
   - 之后把代码默认值改成 mature avGFP


## 9. Phase 3 目前还没有完成的部分

当前代码库已经具备：

- 迭代优化器循环
- 内存中的 `ExperimentMemory`
- surrogate prediction
- `prediction_std`
- hybrid scoring

但还没有完整具备：

- 持久化到磁盘或数据库的 experiment memory
- 湿实验结果导入
- surrogate 自动重训练
- 模型版本晋升流程
- 带不确定性感知的 acquisition logic

因此下一步应该是做一个 Phase 3 MVP，而不是直接做完整的 active-learning 平台。


## 10. Phase 2 和 Phase 3 的推荐分界线

只有在以下三件事都完成后，才能把 Phase 2 视为正式结束：

1. `.env` 已更新
2. 服务已重启
3. 在线冒烟测试通过

这三项完成后，就可以进入 Phase 3 MVP 的实现。


## 11. 完成这份文档后的下一项建议任务

完成这份检查清单后，下一步最具体的实现目标应当是：

1. 持久化 experiment memory
2. 导入湿实验标签
3. 将 surrogate 重训练到新的版本化目录
4. 切换当前生效的模型版本

这就是最小可用的 active-learning 循环。
