# ESM3 Agent 组会演示操作指南

这份文档用于你在组会上通过当前这套 Agent 系统，系统性介绍 **ESM3 能做什么**，并保证你可以按步骤、按页面、按示例完成完整演示。

---

## 1. 演示目标

本次演示不是单纯展示某个 API 能返回什么，而是要回答下面这个问题：

> **ESM3 作为 sequence / structure / function 三轨统一模型，如何在 Agent 系统中变成一个可操作、可组合、可迭代的蛋白设计平台？**

建议你把演示重点放在以下 7 类能力上：

1. `Sequence generation`（序列生成）
2. `Structure prediction`（结构预测）
3. `Inverse folding`（逆折叠）
4. `Function conditioned generation`（功能条件化生成）
5. `Multi-modal reasoning`（多模态推理）
6. `Iterative design`（迭代设计）
7. `Evolution simulation`（进化模拟）

---

## 2. 建议的演示总逻辑

推荐按下面顺序展示：

1. 先证明系统已经真正连通到本地真实 ESM3
2. 再展示 ESM3 的基础能力：
   - 序列生成
   - 结构预测
3. 再展示扩展能力：
   - 逆折叠
   - 功能条件化生成
4. 最后展示 Agent 组合能力：
   - 多模态推理
   - 迭代设计
   - 进化模拟

这样组里的人会更容易理解：

- **先看模型能力**
- **再看系统能力**

---

## 3. 会前准备

### 3.1 在服务器上启动服务

进入项目目录后执行：

```bash
./start_all.sh
```

检查状态：

```bash
./status_all.sh
```

如果你想会前做一次完整自检：

```bash
./smoke_test.sh
```

你希望看到：

- `ESM3 常驻服务` 正常
- `Protein Agent API` 正常
- 冒烟测试通过

---

### 3.2 在本机建立 SSH 隧道

在你本机 Windows PowerShell 中执行：

```powershell
ssh -o ExitOnForwardFailure=yes -N -L 8080:127.0.0.1:8000 -L 8081:127.0.0.1:8001 tio
```

说明：

- 这个窗口在输入密码后看起来“卡住”是正常的
- 它不是卡住，而是在**保持端口转发**
- **不要关闭这个窗口**

---

### 3.3 本机浏览器预先打开的页面

建议会前把这 3 个页面都打开：

- 聊天工作台：
  - `http://127.0.0.1:8080/`
- Agent API 文档：
  - `http://127.0.0.1:8080/docs`
- ESM3 服务文档：
  - `http://127.0.0.1:8081/docs`

---

## 4. 你开场可以这样介绍

你可以直接这样说：

> “今天我不是只演示一个蛋白生成 API，而是演示 ESM3 作为一个 sequence、structure、function 三轨统一模型，如何通过 Agent 系统被组织成一个可交互、可组合、可迭代优化的蛋白设计平台。”

你也可以补一句：

> “所以今天重点不是某个按钮，而是 ESM3 这些底层能力如何被系统化地串起来。”

---

## 5. 演示步骤（推荐现场顺序）

---

### 步骤 0：先证明系统在线

#### 现场操作

1. 打开 `http://127.0.0.1:8080/`
2. 展示左侧状态卡
3. 打开 `http://127.0.0.1:8080/docs`
4. 打开 `http://127.0.0.1:8081/docs`

#### 你可以这样讲

- `8080` 是 Agent 层
- `8081` 是底层真实 ESM3 模型服务层
- 当前展示的不是 mock，而是真实本地 ESM3

---

### 步骤 1：Sequence generation（序列生成）

#### 页面

`http://127.0.0.1:8081/docs`

#### 接口

`POST /generate_sequence`

#### 示例输入

```json
{
  "prompt": "MSKGEELFTGVV",
  "num_candidates": 2,
  "temperature": 0.8
}
```

#### 预期现象

返回 2 条候选序列，例如：

- `MSKGEELFTGVS`
- `MSKLEELFTGVV`

#### 建议解说

> “这一步说明 ESM3 在 sequence track 上不仅能理解序列，还能生成新的候选序列。”

---

### 步骤 2：Structure prediction（结构预测）

#### 页面

`http://127.0.0.1:8081/docs`

#### 接口

`POST /predict_structure`

#### 示例输入

```json
{
  "sequence": "MSKGEELFTGVV"
}
```

#### 预期现象

返回结构信息摘要，例如：

- `shape: [12, 37, 3]`
- `confidence: ...`

#### 建议解说

> “这说明 ESM3 不是只会做 sequence continuation，它还能在 structure track 上给出结构表示或结构预测结果。”

---

### 步骤 3：Inverse folding（逆折叠）

#### 页面

推荐直接在聊天工作台：

`http://127.0.0.1:8080/`

切换到：

- `逆折叠`

#### 推荐输入方式

优先用服务器上的 PDB 路径，例如：

```text
/mnt/disk3/tio_nekton4/esm3/data/lutn.pdb
```

参数建议：

- 候选数：`2`
- 温度：`0.8`
- `num_steps`：`1`

#### 备选方式

- 上传 `.pdb` 文件
- 粘贴 `PDB 文本`

#### 建议解说

> “逆折叠的意思是：给定结构，反推出 compatible sequence。也就是说 ESM3 不只是 sequence→structure，它还能 structure→sequence。”

---

### 步骤 4：Function conditioned generation（功能条件化生成）

#### 页面

仍然在聊天工作台：

`http://127.0.0.1:8080/`

切换到：

- `功能条件化生成`

#### 示例输入

- 目标长度：`128`
- 候选数：`2`
- 温度：`0.8`
- `num_steps`：`8`
- 功能关键词：

```text
fluorescent protein
```

你也可以点击：

- `插入注释模板`

再修改生成的注释 JSON。

#### 建议解说

> “这一步说明 ESM3 不只是按序列或结构条件生成，也能按功能目标来生成候选序列。”

---

### 步骤 5：Iterative design（迭代设计）

#### 页面

`http://127.0.0.1:8080/`

切回：

- `迭代设计`

#### 输入任务

```text
请自动设计 GFP 并迭代优化
```

#### 参数建议

- 最大迭代轮数：`3`
- 每轮候选数：`4`
- 提前停止容忍轮数：`2`

#### 预期现象

页面会展示：

- 聊天式结果总结
- 最佳序列
- 候选历史
- 完整 JSON

#### 建议解说

> “这里展示的不是单次模型调用，而是 Agent orchestration：生成、评估、筛选、再迭代。”

---

### 步骤 6：Multi-modal reasoning（多模态推理）

#### 页面

仍在 `迭代设计` 模式下。

#### 现场操作

在高级输入区域同时填写：

- 文本任务：

```text
请基于给定结构和功能约束继续优化 GFP
```

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

- 目标长度：

```text
128
```

#### 预期现象

右侧结果摘要里会显示：

- `输入模态`

正常情况下你会看到：

```text
sequence, structure, function
```

#### 建议解说

> “这一步展示的不是某一个孤立接口，而是文本目标、序列、结构和功能约束一起进入同一个设计流程。”

---

### 步骤 7：Evolution simulation（进化模拟）

#### 页面

仍在 `迭代设计` 模式下。

#### 参数建议

把迭代参数改成：

- 最大迭代轮数：`4`
- 每轮候选数：`4`
- 提前停止容忍轮数：`3`
- 种群大小：`12`
- 精英保留数：`2`
- 父代池大小：`4`
- 每个父代突变位点数：`3`

任务输入：

```text
请自动设计 GFP，并用更偏进化搜索的方式迭代优化
```

#### 预期现象

右侧会出现：

- `代际统计`

每一代会显示：

- `best score`
- `average score`
- `worst score`
- `population`
- `elite`
- `parent pool`
- `mutations`

#### 建议解说

> “这一步已经不是简单的 top1 再改一下，而是一个 population-based search。可以把它理解成蛋白设计里的进化式优化框架。”

---

## 6. 你可以怎么总结这 7 项能力

你可以在最后用下面这段话总结：

- `Sequence generation`
  - 给 seed 或 prompt，生成候选蛋白序列

- `Structure prediction`
  - 给序列，返回结构表示或结构预测结果

- `Inverse folding`
  - 给结构，反推出 compatible sequence

- `Function conditioned generation`
  - 给功能标签或功能约束，生成候选序列

- `Multi-modal reasoning`
  - 同时综合文本目标、序列、结构、功能输入进行设计

- `Iterative design`
  - 自动做生成、评估、选优和多轮优化

- `Evolution simulation`
  - 用种群、父代池、精英保留和突变参数做进化式搜索

---

## 7. 推荐你现场说的核心句子

你可以直接照着说：

> “ESM3 不是只会续写蛋白序列，它同时覆盖了 sequence、structure、function 三个层面。”

> “而 Agent 的意义，是把这些底层能力从一个个孤立接口，变成一个可组合、可多轮优化、可面向真实蛋白设计任务的工作流系统。”

---

## 8. 建议的 10–15 分钟组会顺序

### 版本 A：标准版

1. 1 分钟：系统定位
2. 1 分钟：展示 `8080/`、`8080/docs`、`8081/docs`
3. 2 分钟：Sequence generation
4. 2 分钟：Structure prediction
5. 2 分钟：Inverse folding
6. 2 分钟：Function conditioned generation
7. 2 分钟：Iterative design + Multi-modal reasoning
8. 2 分钟：Evolution simulation

### 版本 B：时间紧张版

1. 在线状态
2. Sequence generation
3. Structure prediction
4. Iterative design
5. Multi-modal reasoning
6. Evolution simulation

如果时间特别短：

- `Inverse folding` 和 `Function conditioned generation` 可以改成只展示界面和接口，不深跑

---

## 9. 会前彩排清单

会前建议你按这个顺序过一遍：

```bash
./status_all.sh
./smoke_test.sh
```

然后浏览器确认：

- `http://127.0.0.1:8080/`
- `http://127.0.0.1:8080/docs`
- `http://127.0.0.1:8081/docs`

并至少实际点一次：

- `迭代设计`
- `逆折叠`
- `功能条件化生成`

---

## 10. 现场失败时怎么救场

如果某一步现场不稳定，不要卡在排障上，按下面顺序兜底：

### 最稳的能力

- `Sequence generation`
- `Structure prediction`
- `Iterative design`

### 可用来“展示接口已接好”的能力

- `Inverse folding`
- `Function conditioned generation`

如果它们现场不稳定：

- 直接切到：
  - `http://127.0.0.1:8080/docs`
  - `http://127.0.0.1:8081/docs`
- 展示接口已经进入系统，并说明能力位置和工作流关系

### 一定不要做的事

- 不要现场长时间排日志
- 不要长时间重启服务
- 不要把组会变成 debugging session

---

## 11. 最后的收束话术

你可以用下面这段话结束：

> “今天我展示的不是一个单点模型 API，而是一个以 ESM3 为核心、把 sequence、structure、function 三类能力统一起来，并通过 Agent 完成组合推理、迭代设计和进化式优化的系统。”

> “也就是说，ESM3 的价值不只是‘它能生成什么’，更是‘这些能力如何被组织成一个可操作的蛋白设计平台’。”

---

## 12. 你现场最需要记住的页面

- 聊天工作台：
  - `http://127.0.0.1:8080/`
- Agent API 文档：
  - `http://127.0.0.1:8080/docs`
- ESM3 服务文档：
  - `http://127.0.0.1:8081/docs`

如果只记 1 个页面，就记：

- `http://127.0.0.1:8080/`

因为这里已经能把：

- 迭代设计
- 多模态推理
- 逆折叠
- 功能条件化生成
- 进化式参数调节

集中到一个工作台里。

