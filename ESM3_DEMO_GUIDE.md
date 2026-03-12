# ESM3 Demo Guide

这份文档是当前仓库里 **唯一建议继续保留的演示文档**。它合并了组会演示稿和 `8080` 工作台演示手册，保留一套统一的现场流程。

## 1. 演示目标

现场真正要讲清楚的不是“某个接口能返回什么”，而是：

> ESM3 的 `sequence / structure / function` 能力，如何在这个仓库里被组织成一个可交互、可组合、可迭代优化的蛋白设计系统。

建议重点展示 6 类能力：

1. `Iterative design`
2. `Structure-aware evaluation`
3. `Inverse folding`
4. `Function conditioned generation`
5. `Multi-modal reasoning`
6. `Evolution simulation`

## 2. 会前准备

### 服务自检

```bash
./start_all.sh
./status_all.sh
./smoke_test.sh
```

### SSH 隧道

如果你通过本机转发访问：

```powershell
ssh -o ExitOnForwardFailure=yes -N -L 8080:127.0.0.1:8000 -L 8081:127.0.0.1:8001 <your_host_alias>
```

### 建议预先打开的页面

- 工作台：`http://127.0.0.1:8080/`
- Agent API docs：`http://127.0.0.1:8080/docs`
- ESM3 runtime docs：`http://127.0.0.1:8081/docs`

如果你想做“只用一个页面”的演示，也可以只保留：

- `http://127.0.0.1:8080/`

## 3. 推荐的 10 到 15 分钟顺序

1. 先证明系统在线
2. 展示最基础的 `Iterative design`
3. 展示 `Inverse folding`
4. 展示 `Function conditioned generation`
5. 回到 `Iterative design`，展示 `Multi-modal reasoning`
6. 最后展示 `Evolution simulation`

如果时间很短，就保留：

1. 系统在线
2. `Iterative design`
3. `Inverse folding`
4. `Multi-modal reasoning`

## 4. 步骤 0：先证明系统在线

在现场至少展示：

- `http://127.0.0.1:8080/`
- `http://127.0.0.1:8080/docs`
- `http://127.0.0.1:8081/docs`

你可以直接说：

> `8080` 是 Agent 层，`8081` 是底层 ESM3 runtime；当前演示的不是 mock，而是真实链路。

## 5. 步骤 1：Iterative Design

页面：

- `http://127.0.0.1:8080/`
- 模式：`迭代设计`

参数建议：

- 最大迭代轮数：`3`
- 每轮候选数：`4`
- 提前停止容忍轮数：`2`
- 种群大小：`8`
- 精英保留数：`2`
- 父代池大小：`4`
- 每个父代突变位点数：`3`

任务：

```text
请自动设计 GFP 并迭代优化
```

重点展示：

- `最新结果摘要`
- `最佳序列`
- `候选历史`
- `完整 JSON`

要点：

- 这不是单次模型调用
- 是生成、评估、筛选、再迭代的工作流

## 6. 步骤 2：Inverse Folding

页面：

- `http://127.0.0.1:8080/`
- 模式：`逆折叠`

推荐输入：

```text
/mnt/disk3/tio_nekton4/esm3/data/lutn.pdb
```

参数：

- 候选数：`2`
- 温度：`0.8`
- `num_steps = 1`

任务：

```text
请根据这个结构生成两个候选序列
```

要点：

- 说明系统支持 `structure -> sequence`
- 这是蛋白设计里很关键的一类能力

## 7. 步骤 3：Function Conditioned Generation

页面：

- `http://127.0.0.1:8080/`
- 模式：`功能条件化生成`

参数：

- 目标长度：`128`
- 候选数：`2`
- 温度：`0.8`
- `num_steps = 8`
- 功能关键词：

```text
fluorescent protein
```

任务：

```text
请生成两个候选序列
```

要点：

- 说明 ESM3 不只是按序列 continuation 生成
- 还可以按功能目标约束生成

## 8. 步骤 4：Multi-modal Reasoning

页面：

- `http://127.0.0.1:8080/`
- 模式：`迭代设计`

高级输入同时填写：

- 参考序列：

```text
MSKGEELFTGVV
```

- 结构路径：

```text
/mnt/disk3/tio_nekton4/esm3/data/lutn.pdb
```

- 功能关键词：

```text
fluorescent protein
```

- 目标长度：`128`

任务：

```text
请基于给定结构和功能约束继续优化 GFP
```

重点展示：

- `输入模态`
- `完整 JSON`

正常情况下会看到：

```text
sequence, structure, function
```

## 9. 步骤 5：Evolution Simulation

仍在 `迭代设计` 模式下，把参数改成：

- 最大迭代轮数：`4`
- 每轮候选数：`4`
- 提前停止容忍轮数：`3`
- 种群大小：`12`
- 精英保留数：`2`
- 父代池大小：`4`
- 每个父代突变位点数：`3`

任务：

```text
请自动设计 GFP，并用更偏进化搜索的方式迭代优化
```

重点展示：

- `代际统计`
- 每一代的 `best / avg / worst`

要点：

- 当前系统已经不是简单 top-1 反复突变
- 而是 population-based evolutionary search

## 10. 如果现场出问题，优先保住什么

优先保住这三项：

1. `Iterative design`
2. `Inverse folding`
3. `Function conditioned generation`

如果多模态或进化统计现场不稳定：

- 直接切到 `完整 JSON`
- 强调系统已经支持这些输入和返回结构
- 不要把演示变成排障会

## 11. 结尾可以怎么说

你可以直接用这句：

> 今天展示的不是一个单点 API，而是 ESM3 的 `sequence / structure / function` 三类能力，如何被组织成一个可交互、可多模态、可迭代、可进化式搜索的蛋白设计系统。

## 12. 这份文档合并了哪些旧文件

以下历史文档已被本指南吸收，不建议继续单独维护：

- `ESM3_GROUP_MEETING_GUIDE.md`
- `ESM3_WORKSPACE_8080_DEMO_GUIDE.md`
