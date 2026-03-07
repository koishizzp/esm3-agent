# ESM3 Agent

蛋白质AI助手，OpenAI API兼容。

## 给零基础用户的最简用法（推荐）

目标：让不会编程的人也能直接用。

### 第一步：只改 1 个配置文件

编辑 `config.yaml`（或你自己的环境变量文件），至少确认以下字段：

- `PORT`：服务端口（默认 `:8080`）
- `PYTHON_PATH`：ESM3 的 Python 解释器
- `SCRIPT_DIR`：ESM3 项目目录
- `DB_PATH`：默认序列数据库路径（SQLite）

### 第二步：启动服务

```bash
./start.sh
./status.sh
```

### 第三步：在聊天里“说人话”

你可以通过 OpenAI 兼容接口发送自然语言：

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"帮我检查一下运行环境"}]
  }'
```

---

## 上游LLM（真实 Function Calling）

Agent 支持调用 OpenAI 兼容接口进行真实工具选择（function calling）。

```bash
export UPSTREAM_API="https://api.openai.com/v1/chat/completions"
export UPSTREAM_KEY="<your_api_key>"
export UPSTREAM_MODEL="gpt-4o-mini"
```

如果 `UPSTREAM_KEY` 为空，会自动回退到本地关键词匹配逻辑。

---

## 详细使用说明（包含文件/数据库分析 + 约束生成）

### 1) 配置环境变量

```bash
export UPSTREAM_API="https://api.openai.com/v1/chat/completions"
export UPSTREAM_KEY="sk-xxxx"
export UPSTREAM_MODEL="gpt-4o-mini"

# ESM3 本地执行环境
export PYTHON_PATH="/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python"
export SCRIPT_DIR="/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction"

# 可选：默认数据库
export DB_PATH="./data/sequences.db"
```

### 2) 启动与健康检查

```bash
./start.sh
curl http://localhost:8080/health
```


### 2.1 服务器和本地浏览器不通时，怎么打开这个地址？

你看到的 `http://localhost:8080/v1/chat/completions` 里，`localhost` 指的是“当前机器自己”。

- 在服务器终端里访问 `localhost:8080`：是访问服务器自己。
- 在你本地电脑浏览器访问 `localhost:8080`：是访问你自己的电脑，不是服务器。

所以如果你在本地浏览器打不开，通常要用下面三种方式之一：

#### 方式A（最推荐）：SSH 端口转发（无需改服务）

在你**本地电脑**终端运行：

```bash
ssh -L 8080:127.0.0.1:8080 <你的服务器用户名>@<你的服务器IP>
```

然后保持这个 SSH 窗口不关，再在本地浏览器打开：

- `http://localhost:8080/health`

这时你本地的 `localhost:8080` 会被转发到服务器的 `127.0.0.1:8080`。

#### 方式B：直接用服务器 IP + 放通防火墙端口

1) 确认服务已启动并监听 8080

```bash
./start.sh
ss -lntp | rg 8080
```

2) 云服务器安全组 / 防火墙放通 TCP 8080（来源建议限制为你的办公IP）

3) 本地浏览器打开：

- `http://<服务器公网IP>:8080/health`

> 安全提醒：生产环境不建议直接暴露 8080 到公网，至少要加访问控制。

#### 方式C：反向代理（Nginx/Caddy）

把域名（如 `https://esm3.yourdomain.com`）反代到 `127.0.0.1:8080`，再通过 HTTPS 访问。适合长期对外提供服务。

#### 快速自检命令（在服务器执行）

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/v1/models
```

如果这里返回正常，而你本地打不开，基本就是“网络连通/端口映射”问题，不是程序本身问题。

### 3) 序列分析（3 种来源）

#### 3.1 直接输入序列

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"分析序列 MKTVRQERLKDLLEK"}]
  }'
```

#### 3.2 从文件分析（FASTA / 纯文本）

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"请分析文件 /data/sample.fasta 中的蛋白序列"}]
  }'
```

#### 3.3 从数据库分析（SQLite）

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"从数据库读取并分析，db_path=/data/sequences.db, query=SELECT sequence FROM sequences LIMIT 1"}]
  }'
```

### 4) 蛋白生成（可加约束条件）

支持示例约束：
- 长度范围（`min_length`, `max_length`）
- 必须包含 motif（`must_include`）
- 禁用氨基酸（`forbidden_aas`）
- 温度（`temperature`）

自然语言示例：

```bash
curl http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model":"esm3-agent-v1",
    "messages":[{"role":"user","content":"生成一个蛋白，长度180-220，必须包含GSG，不能出现C，温度0.7"}]
  }'
```

> 说明：生成工具本身耗时较长（通常 2-5 分钟）。

### 5) 日志和排错

```bash
# 服务日志
tail -f logs/esm3-agent.log

# 使用日志（包含 tool 决策和耗时）
tail -f logs/usage.log
```

常见问题：
- `tool_args parse failed`：上游模型返回了非 JSON 参数。
- `工具执行错误`：通常是本地 Python/ESM3 环境、文件路径或数据库路径问题。
- 生成很慢：`generate_protein` 正常现象。

---

## 快速命令

```bash
./start.sh
./stop.sh
./restart.sh
./status.sh
```
