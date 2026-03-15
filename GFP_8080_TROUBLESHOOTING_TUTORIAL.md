# GFP 设计与 8080 页面排错教程

Port note:

- `8001` = ESM3 runtime
- `8000` = canonical Python Agent API
- `8080` = local forwarded alias to `8000`, or an optional gateway only

这份教程专门解决你刚刚遇到的两类问题：

1. `500 - auth_unavailable: no auth available`
2. 在 `http://127.0.0.1:8080/` 里做 GFP 设计时，没有真正锁住参考序列和 `SYG` 位点，结果跑偏成非 GFP 候选

---

## 1. 先说结论

你现在最应该做的，不是继续直接点页面重跑，而是按下面顺序处理：

1. 先重启 `8000` 的 Agent API，让最新代码生效
2. 如果你暂时不用外部 LLM，把 `.env` 里的 `OPENAI_*` / `PROTEIN_AGENT_OPENAI_*` 配置清空
3. 再次启动服务
4. 打开 `http://127.0.0.1:8080/`
5. 先清空会话，避免继承上一轮错误最佳序列
6. 在“参考序列”框里显式填入 GFP 序列
7. 在“固定残基”框里显式填入 `63:S, 64:Y, 65:G`
8. 再跑新的 GFP 设计任务

---

## 2. 为什么会报 `auth_unavailable`

这个错误不是 ESM3 本身坏了。

它的真正含义是：

- 你的 Agent 在处理任务时，会先尝试调用外部 LLM 来生成 plan
- 当前 `.env` 里配置了一个 OpenAI 兼容网关
- 这个网关当前没有可用鉴权，所以返回了：

```text
auth_unavailable: no auth available
```

现在代码已经改成：

- 如果外部 LLM 失败，就自动回退到本地确定性 plan

但前提是：

- 你必须重启当前运行中的 Agent 进程

否则页面还在连旧进程，仍然会继续报 500。

---

## 3. 第一步：重启 Agent API

### 如果你是用仓库脚本启动的

在项目根目录执行：

```bash
./stop_all.sh
./start_all.sh
./status_all.sh
```

### 如果你是手动启动的

请停止当前 `8000` 的 Agent 进程，然后重新启动它。

如果你是分开启动：

1. 停掉当前 Agent API
2. 保持 ESM3 runtime 还在
3. 重新启动 Agent API

### 重启后先检查

至少确认：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8001/health
```

都正常。

---

## 4. 第二步：如果暂时不想依赖外部 LLM，就关闭它

打开项目根目录的 `.env`。

把下面这些项清空：

```text
OPENAI_API_KEY=
OPENAI_BASE_URL=
PROTEIN_AGENT_OPENAI_API_KEY=
PROTEIN_AGENT_OPENAI_BASE_URL=
```

可选：

```text
OPENAI_MODEL=
PROTEIN_AGENT_LLM_MODEL=
```

也可以保留模型名，只清空 key 和 base URL。  
关键是不要让系统继续去请求那个当前不可用的外部网关。

改完之后，再重启一次 Agent API。

这样做之后，规划器会直接走本地 fallback，不再因为外部 LLM 鉴权失败而中断整个设计任务。

---

## 5. 第三步：打开 8080 页面前，先清理上下文

进入：

```text
http://127.0.0.1:8080/
```

然后做两件事：

### A. 点击“清空会话”

原因：

- 页面会保留上一轮结果
- 如果上一轮最佳序列已经跑偏，后续继续追问或继续设计时可能把它带进去

### B. 检查“自动带上上一轮最佳序列”

如果你刚做完清空会话，这项影响会变小。  
但为了避免污染新一轮任务，建议你这次先：

- 暂时取消勾选“自动带上上一轮最佳序列”

等你确认当前这轮结果正常之后，再打开也不迟。

---

## 6. 第四步：正确填写 GFP 设计页面

现在不要只把序列粘在任务文本里。

虽然最新代码已经支持“从任务文本里自动识别长氨基酸序列”，但最稳的方式依然是：

- **把序列明确填进“参考序列”框**

### 推荐填写方式

#### 任务文本

建议写：

```text
请基于给定参考序列和结构继续优化 GFP，强制保留 SYG 色团位点，并优先给出满足硬约束的候选。
```

#### 参考序列

把你的 GFP 序列直接填进：

```text
参考序列（可选）
```

不要只写在任务文本里。

#### 固定残基

在新增加的：

```text
固定残基（可选）
```

里填：

```text
63:S, 64:Y, 65:G
```

也可以每行一个：

```text
63 S
64 Y
65 G
```

如果你还想锁别的位点，也继续往后写，例如：

```text
63:S, 64:Y, 65:G, 96:R
```

#### 结构

如果你确实有结构约束，就把 PDB 路径或 PDB 文本填进去。  
如果没有，先不要乱填。

#### 功能关键词

可以填：

```text
fluorescent protein
```

如果你只是想先确认“锁位点”能不能生效，功能关键词不是必须项。

---

## 7. 第五步：关于你这次给的 GFP 序列，要特别注意什么

你刚才贴的那条序列不是当前系统默认的 `236 aa mature avGFP`。

它更像是你自己的 GFP-like 变体，长度是：

```text
234 aa
```

并且它在你当前这条序列里，`SYG` 是落在 `63-65` 位点的。

这意味着：

1. 如果你就是想围绕这条 **234 aa** 的序列继续优化，那么没问题  
   这次应该把它明确填进“参考序列”框，并锁 `63:S, 64:Y, 65:G`

2. 如果你其实想用系统默认那套 **236 aa mature avGFP 坐标体系**，那你就不应该用这条 234 aa 序列做 seed  
   否则你自己心里的坐标和系统的默认 GFP 参考就不是同一套东西

所以你要先选清楚：

### 路线 A：围绕你自己的这条 234 aa GFP 继续优化

做法：

- 参考序列填你的 234 aa 序列
- 固定残基填 `63:S, 64:Y, 65:G`

### 路线 B：围绕系统当前默认的 mature avGFP 体系优化

做法：

- 参考序列改填 mature avGFP 236 aa 序列
- 固定残基仍然填 `63:S, 64:Y, 65:G`

不要把这两条路线混着用。

---

## 8. 第六步：一个最稳的页面操作模板

你可以直接照这个模板填：

### 任务文本

```text
请基于给定参考序列继续优化 GFP，强制保留 SYG 色团位点，只返回满足硬约束的候选，并解释当前最佳候选为什么值得优先验证。
```

### 参考序列

填你这条 234 aa GFP 序列：

```text
MSKGEELFTGVVPILVELDGDVNGHKFSVSGEGEGDATYGKLTKLFICTKGLPVWPTLVSTLSYGVQCFSRYPDHMKQHDFFKSAMPEGYVQERTIFFKDDSNYKTRAEVKFEGDTLVNRIELKGIDFKEDGKILGHKLEYNNSHNVKVMAKQKNGIVVNFKIRHNIEDGSVQLADHYQQNTPIGDGPVLLPDNHYLSTQTALSKDPNEKRDHMVLLEFVTAAGITHGMDELYK
```

### 固定残基

```text
63:S, 64:Y, 65:G
```

### 最大迭代轮数

```text
3
```

### 每轮候选数

```text
4
```

### 提前停止容忍轮数

```text
2
```

### 功能关键词

```text
fluorescent protein
```

如果你只是先测试硬约束是否生效，也可以先把功能关键词留空。

---

## 9. 第七步：跑完以后看哪里

任务执行完成后，不要只看聊天区那几句总结。

重点看右侧：

### A. 最新结果摘要

重点确认：

- 色团位点是不是显示：

```text
SYG 保留
```

### B. 候选历史

看前几名候选的：

- `score`
- `SYG 保留 / 破坏`
- 是否有 `motif penalty`

### C. 完整 JSON

重点看 `best_candidate` 或 `best_sequences` 对应记录里的：

- `metadata.valid_candidate`
- `metadata.motif_intact`
- `metadata.required_motif`
- `metadata.fixed_residue_violations`
- `metadata.motif_penalty`
- `metadata.length_penalty`

如果你看到：

```text
valid_candidate = true
motif_intact = true
fixed_residue_violations = []
```

说明这次锁位点至少在系统里是生效的。

---

## 10. 如果结果里还是出现 `SYG 破坏`

请按下面顺序检查：

### 1. 你是不是还在看旧结果

确认：

- 已清空会话
- 已刷新页面
- 已重启 8000 服务

### 2. 你是不是没有把序列填进“参考序列”框

现在虽然支持任务文本自动识别，但最稳仍然是：

- **明确填参考序列框**

### 3. 你是不是没有填“固定残基”

只在任务文本里写：

```text
强制保留 SYG
```

不如直接填：

```text
63:S, 64:Y, 65:G
```

### 4. 你是不是在继承上一轮错误最佳序列

确认：

- 会话已清空
- “自动带上上一轮最佳序列”已关闭

### 5. 你是不是用了和默认坐标不一致的 seed

如果你给的是自己的 234 aa 变体，就要始终按这条序列的编号理解位点。  
不要一边用自己的序列，一边假定系统还是默认 `236 aa mature avGFP` 的整套上下文。

---

## 11. 如果还是报 500，该怎么判断是哪一层坏了

### 情况 A：还是看到 `auth_unavailable`

说明：

- 你现在跑的仍然是旧 Agent 进程
- 或 `.env` 里外部 LLM 配置还在生效，但进程没有重启

做法：

1. 再次确认 `.env` 已清空外部 LLM 相关 key/base_url
2. 再次重启 Agent API
3. 刷新页面后再试

### 情况 B：`/health` 正常，但设计请求失败

说明：

- ESM3 服务本身不一定坏
- 更可能是 Agent 编排层、约束解析或请求内容有问题

这时优先把右侧错误信息和服务日志拿出来看。

### 情况 C：页面能开，但结果明显不是 GFP

说明：

- 更可能不是服务挂了
- 而是输入上下文没有正确进入系统

优先检查：

- 参考序列是否填了
- 固定残基是否填了
- 会话是否清空
- 是否关闭了自动继承上一轮最佳序列

---

## 12. 最后给你一个最短执行清单

如果你现在就要重新开始，直接照着做：

1. 关闭当前 `8000` Agent 进程
2. 清空 `.env` 里的 `OPENAI_*` / `PROTEIN_AGENT_OPENAI_*`
3. 重启服务
4. 打开 `http://127.0.0.1:8080/`
5. 点击“清空会话”
6. 关闭“自动带上上一轮最佳序列”
7. 在“参考序列”框填你的 234 aa GFP 序列
8. 在“固定残基”框填 `63:S, 64:Y, 65:G`
9. 任务文本写：

```text
请基于给定参考序列继续优化 GFP，强制保留 SYG 色团位点，只返回满足硬约束的候选。
```

10. 发送任务
11. 右侧确认：
    - `SYG 保留`
    - `valid_candidate = true`
    - `fixed_residue_violations = []`

---

## 13. 如果你愿意，我下一步还能继续帮你做什么

如果你下一条把最新一次运行后的：

- 右侧“完整 JSON”
- 或 `run_artifact_path` 对应的 JSON 文件

贴给我，我可以继续帮你做这三件事之一：

1. 帮你判断这次约束是否真的生效
2. 帮你比较前 2 到 5 名候选
3. 帮你把这条 234 aa GFP 变体整理成一套更稳的固定设计模板

