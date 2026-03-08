# 真实 ESM3 接入说明

当前仓库里的 Python `protein_agent` 流程已经支持三种 ESM3 后端模式。

## 后端模式

- `PROTEIN_AGENT_ESM3_BACKEND=http`
  - 连接一个已经运行中的 ESM3 HTTP 服务。
  - 预期接口为：`/generate_sequence`、`/mutate_sequence`、`/predict_structure`。
- `PROTEIN_AGENT_ESM3_BACKEND=local`
  - 直接拉起你配置好的 ESM3 Python 环境，并导入本地部署的 ESM3。
  - 适合你这种“本地有完整 ESM3 仓库 + 权重 + data”的场景。
- `PROTEIN_AGENT_ESM3_BACKEND=auto`
  - 依次尝试 HTTP、本地部署、以及可选的 LLM 生成 Python 兜底。

## 适配你当前目录结构的最小配置

假设你的部署目录是：

```text
esm3/
  weights/
  data/
  esm/
  projects/gfp_reproduction/
```

至少需要设置：

```bash
export PROTEIN_AGENT_ESM3_BACKEND=local
export PROTEIN_AGENT_ESM3_PYTHON_PATH=/path/to/your/esm3/env/bin/python
export PROTEIN_AGENT_ESM3_ROOT=/abs/path/to/esm3
export PROTEIN_AGENT_ESM3_PROJECT_DIR=/abs/path/to/esm3/projects/gfp_reproduction
export PROTEIN_AGENT_ESM3_WEIGHTS_DIR=/abs/path/to/esm3/weights
export PROTEIN_AGENT_ESM3_DATA_DIR=/abs/path/to/esm3/data
export PROTEIN_AGENT_ESM3_MODEL_NAME=esm3-open
```

如果你的项目里已经暴露了明确的可调用函数，也可以额外指定入口：

```bash
export PROTEIN_AGENT_ESM3_GENERATE_ENTRYPOINT=/abs/path/to/script.py:generate
export PROTEIN_AGENT_ESM3_MUTATE_ENTRYPOINT=/abs/path/to/script.py:mutate
export PROTEIN_AGENT_ESM3_STRUCTURE_ENTRYPOINT=/abs/path/to/script.py:predict_structure
```

## 可选：启用 LLM 生成 Python 兜底

如果你本地项目暂时没有稳定暴露生成/突变/结构预测入口，可以允许 Agent 在运行时生成一个很小的 Python 辅助脚本来完成调用：

```bash
export PROTEIN_AGENT_ALLOW_GENERATED_PYTHON=true
export PROTEIN_AGENT_OPENAI_API_KEY=<your_llm_key>
export PROTEIN_AGENT_OPENAI_BASE_URL=<openai-compatible-base-url>
export PROTEIN_AGENT_LLM_MODEL=gpt-4o-mini
```

这个能力默认是关闭的，因为它会在你配置好的 ESM3 环境里执行 LLM 生成的 Python。

## 如果还要继续精调，最有价值的信息

如果后面还要继续做更深的定制，这几项信息最有用：

1. `esm3/` 根目录的绝对路径。
2. 能正常 `import torch` 和本地 `esm` 包的 Python 可执行文件绝对路径。
3. 你的项目脚本里是否已经有可导入的函数；如果有，对应函数名是什么。
4. 如果你已经有现成的 HTTP 服务，再给一条成功的 `curl` 请求和响应。

## 推荐启动顺序

1. 启动 Python Agent API：

```bash
uvicorn protein_agent.api.main:app --host 0.0.0.0 --port 8000
```

2. 提交任务：

```bash
curl -X POST http://127.0.0.1:8000/design_protein \
  -H 'Content-Type: application/json' \
  -d '{"task":"Automatically design GFP and iteratively optimize it", "max_iterations": 5, "candidates_per_round": 6}'
```

如果本地部署加载失败，桥接层会返回更详细的错误信息，比如 `wrapper_attempts` 或模型加载错误，方便继续定位问题。

## 结合你当前机器的具体命令

根据你已经提供的路径，你可以直接这样配置：

```bash
cd /mnt/disk3/tio_nekton4/esm3-agent
cp .env.local.example .env

export PROTEIN_AGENT_ESM3_PYTHON_PATH=/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python
export PROTEIN_AGENT_ESM3_ROOT=/mnt/disk3/tio_nekton4/esm3
export PROTEIN_AGENT_ESM3_PROJECT_DIR=/mnt/disk3/tio_nekton4/esm3/projects/gfp_reproduction
export PROTEIN_AGENT_ESM3_WEIGHTS_DIR=/mnt/disk3/tio_nekton4/esm3/weights
export PROTEIN_AGENT_ESM3_DATA_DIR=/mnt/disk3/tio_nekton4/esm3/data
export PROTEIN_AGENT_ESM3_MODEL_NAME=esm3-open
export PROTEIN_AGENT_ESM3_DEVICE=cuda
```

先启动常驻的本地 ESM3 服务：

```bash
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -m uvicorn protein_agent.esm3_server.server:app --host 0.0.0.0 --port 8001
```

然后在另一个终端启动 Agent API：

```bash
export PROTEIN_AGENT_ESM3_BACKEND=http
export PROTEIN_AGENT_ESM3_SERVER_URL=http://127.0.0.1:8001
/mnt/disk3/tio_nekton4/miniconda3/envs/esm3_env/bin/python -m uvicorn protein_agent.api.main:app --host 0.0.0.0 --port 8000
```

快速检查命令：

```bash
curl http://127.0.0.1:8001/health
curl http://127.0.0.1:8000/health
curl -X POST http://127.0.0.1:8000/design_protein \
  -H 'Content-Type: application/json' \
  -d '{"task":"Automatically design GFP and iteratively optimize it", "max_iterations": 3, "candidates_per_round": 4}'
```

注意：`curl http://127.0.0.1:8080/health` 只能说明旧服务是活的，不能说明 Python `protein_agent` 已经成功接通真实 ESM3。

## 直接用脚本启动

仓库根目录已经附带两个 Ubuntu 启动脚本：

- `start_esm3_server.sh`：读取 `.env`，启动本地常驻 ESM3 服务。
- `start_agent.sh`：读取 `.env`，启动 Python `protein_agent` API。
- `start_all.sh`：一键启动上面两个服务，先等 ESM3 健康检查通过，再启动 Agent；按 `Ctrl-C` 会一起停止。

推荐用法：

```bash
chmod +x start_esm3_server.sh start_agent.sh
./start_esm3_server.sh
```

另开一个终端：

```bash
./start_agent.sh
```

如果你想一条命令同时启动两个服务：

```bash
./start_all.sh
```

这个脚本会：

- 自动读取 `.env`
- 先启动本地 ESM3 服务
- 等 `http://127.0.0.1:8001/health` 就绪
- 再启动 Agent API
- 把日志分别写到 `logs/esm3_server.log` 和 `logs/protein_agent.log`
- 当你按下 `Ctrl-C` 时一起清理两个进程

如果你想改监听端口，也可以临时覆盖：

```bash
PROTEIN_AGENT_ESM3_SERVER_PORT=8002 ./start_esm3_server.sh
PROTEIN_AGENT_API_PORT=8003 ./start_agent.sh
```

对于 `start_all.sh`，也同样支持：

```bash
PROTEIN_AGENT_ESM3_SERVER_PORT=8002 PROTEIN_AGENT_API_PORT=8003 ./start_all.sh
```
