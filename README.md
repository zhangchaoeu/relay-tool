# Hermes Relay & Gateway

本仓库包含两个组件，共同构成**反向 WebSocket 远程 MCP 中继系统**：

| 组件 | 运行主机 | 职责 |
|------|----------|------|
| **Hermes Relay**（`hermes_relay/`） | 32 号机 | 主动连接 33，管理并中继 MCP 服务；本地提供 HTTP Admin API 供手动配置 |
| **Hermes Gateway**（`hermes_gateway/`） | Linux/Mac 33 号机 | 接受 32 的连接，暴露 `call_worker()` API 供 Hermes 调用 |

> English: The repo contains a reverse-WebSocket pair. The Relay (host 32) dials out to the Gateway (host 33) and acts as a pure MCP relay agent. Hermes on host 33 calls `call_worker()` or the convenience `HermesTools` wrappers to dispatch MCP tasks. Host 32 also exposes a local HTTP admin API so operators can manually configure MCP servers directly.

---

## Hermes Gateway（运行在 33 上）

### 功能

- 接受 32 的 WebSocket 反向连接
- 校验 `agent_id` 和 `token`
- 维护单 worker 在线状态、最近心跳、capabilities
- 核心方法 `call_worker(action, payload, timeout)`
  - 自动生成 `task_id`（uuid4）
  - 发送 `task` 消息
  - 等待对应 `task_result`（支持超时）
  - worker 不在线时抛 `WorkerOfflineError`
- `HermesTools` 封装：`relay_mcp_invoke`、`relay_mcp_tools`、`relay_mcp_start`、`relay_mcp_stop`、`relay_mcp_status`、`relay_mcp_register`、`relay_mcp_unregister`、`relay_mcp_logs`

### 项目结构

```text
hermes_gateway/
  __init__.py
  __main__.py     # 启动入口
  config.py       # 配置模型
  state.py        # 单 worker 运行时状态
  gateway.py      # call_worker() 核心 + 消息处理
  server.py       # WebSocket 服务端（注册/心跳/分发）
  tools.py        # Hermes 工具封装函数
gateway_config.example.json
```

### 配置

```bash
cp gateway_config.example.json gateway_config.json
# 修改 worker_token 等字段
```

`gateway_config.json` 字段：

- `host`：监听地址（默认 `0.0.0.0`）
- `port`：监听端口（默认 `8765`）
- `worker_agent_id`：预期的 worker ID（`"relay-32"`）
- `worker_token`：鉴权 token，必须与 Relay 端一致
- `default_task_timeout_seconds`：任务默认超时（秒）
- `heartbeat_timeout_seconds`：心跳超时（秒，供上层监控用）

### 启动

```bash
python -m hermes_gateway --config gateway_config.json
```

### 在 Hermes 中使用

```python
from hermes_gateway.config import load_config
from hermes_gateway.gateway import Gateway
from hermes_gateway.tools import HermesTools

config = load_config("gateway_config.json")
gateway = Gateway(config)
tools = HermesTools(gateway)

# 直接调用
result = await gateway.call_worker("mcp.invoke", {
    "name": "filesystem",
    "tool_name": "read_file",
    "arguments": {"path": "/workspace/test.txt"}
})

# 或使用工具封装
result = await tools.relay_mcp_invoke("filesystem", "read_file", {"path": "/workspace/test.txt"})
entries = await tools.relay_mcp_tools("filesystem")
await tools.relay_mcp_start("filesystem")
await tools.relay_mcp_stop("filesystem")
status = await tools.relay_mcp_status()
```

### call_worker 错误处理

| 异常 | 原因 |
|------|------|
| `WorkerOfflineError` | worker 未连接 |
| `TimeoutError` | 任务超时未返回 |
| `RuntimeError` | worker 返回 `ok=False` |

---

## Hermes Relay（运行在 32 上）

Hermes Relay 是运行在 **32 号机**上的纯 MCP 中继 worker。它**不提供任何 Windows 特定操作**（无文件系统、无 PowerShell），只负责：

1. 通过**反向 WebSocket 长连接**主动连接 33 号机，接收 MCP 任务并回传结果
2. 本地管理 MCP server 进程（启动/停止/重启/状态/日志/调用）
3. 暴露**本地 HTTP Admin API**，供 32 号机上的操作人员手动配置 MCP server（注册/注销/启停）

> English: Hermes Relay is a pure MCP relay worker running on host 32. It has no Windows-specific operations. It dials host 33, handles MCP tasks, and exposes a local HTTP admin API for manual MCP configuration on host 32.

## 功能范围（Relay）

- WebSocket worker
  - 启动后主动连接 `ws_server_url`
  - 发送 `register`
  - 定期发送 `heartbeat`
  - 接收 `task` 并返回 `task_result`
  - 自动重连
- MCP 管理能力（通过 WebSocket relay 供 33 使用）
  - `mcp.register`
  - `mcp.unregister`
  - `mcp.start`
  - `mcp.stop`
  - `mcp.restart`
  - `mcp.status`
  - `mcp.logs`
  - `mcp.tools`
  - `mcp.invoke`
- 本地 HTTP Admin API（供 32 号机本地手动配置）
  - 见下方 [Admin API](#admin-api本地手动配置) 章节

## 技术栈

- Python 3.11+
- asyncio
- websockets
- pydantic
- psutil

## 项目结构（Relay）

```text
hermes_relay/
  __main__.py                # 入口
  config.py                  # 配置模型与加载
  admin.py                   # 本地 HTTP Admin API
  dispatcher.py              # task action 分发
  worker.py                  # WebSocket 长连接 worker
  mcp/
    manager.py               # MCP 注册、托管、状态、工具调用
    protocol.py              # stdio MCP 最小客户端实现
tests/
  test_dispatcher.py
  test_gateway.py
config.example.json
servers.example.json
mock_ws_server.py
```

## 安装（Relay）

```bash
python -m pip install -r requirements.txt
```

## 配置（Relay）

复制并修改示例配置：

```bash
cp config.example.json config.json
```

`config.json` 字段：

- `ws_server_url`：33 号机 Gateway 地址
- `agent_id`：本机标识（如 `"relay-32"`）
- `agent_name`：显示名称
- `worker_token`：鉴权 token，必须与 Gateway 端一致
- `heartbeat_interval_seconds`：心跳间隔（秒）
- `reconnect_interval_seconds`：断线重连间隔（秒）
- `mcp_request_timeout_seconds`：MCP 请求超时（秒）
- `registry_file`：MCP 注册表持久化文件路径
- `log_dir`：MCP server 日志目录
- `admin_host`：Admin HTTP API 监听地址（默认 `"127.0.0.1"`）
- `admin_port`：Admin HTTP API 监听端口（默认 `8766`）

## 启动（Relay）

```bash
python -m hermes_relay --config config.json
```

启动后同时运行：
- WebSocket worker（连接 33 号机 Gateway）
- 本地 HTTP Admin API（默认 `http://127.0.0.1:8766`）

---

## Admin API（本地手动配置）

Admin API 运行在 32 号机本地，供操作人员直接管理 MCP server，无需通过 33 号机。

### 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/mcp/status` | 列出所有已注册 MCP server 及其状态 |
| `GET` | `/mcp/{name}/status` | 查询指定 server 的状态 |
| `POST` | `/mcp/register` | 注册新 MCP server（JSON body） |
| `DELETE` | `/mcp/{name}` | 注销 MCP server（若运行中先停止） |
| `POST` | `/mcp/{name}/start` | 启动指定 MCP server |
| `POST` | `/mcp/{name}/stop` | 停止指定 MCP server |
| `POST` | `/mcp/{name}/restart` | 重启指定 MCP server |
| `GET` | `/mcp/{name}/logs` | 查看日志（`?lines=100`） |
| `GET` | `/mcp/{name}/tools` | 列出 MCP server 提供的工具（需已启动） |

### 使用示例

```bash
# 查看所有 MCP server 状态
curl http://127.0.0.1:8766/mcp/status

# 注册新 MCP server
curl -X POST http://127.0.0.1:8766/mcp/register \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "filesystem",
    "command": "npx",
    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
    "cwd": "/workspace",
    "env": {},
    "auto_start": true
  }'

# 启动 server
curl -X POST http://127.0.0.1:8766/mcp/filesystem/start

# 查看可用工具
curl http://127.0.0.1:8766/mcp/filesystem/tools

# 查看日志（最近 50 行）
curl 'http://127.0.0.1:8766/mcp/filesystem/logs?lines=50'

# 停止并注销
curl -X POST http://127.0.0.1:8766/mcp/filesystem/stop
curl -X DELETE http://127.0.0.1:8766/mcp/filesystem
```

---

## 消息协议

### register (worker -> server)

```json
{
  "type": "register",
  "agent_id": "relay-32",
  "agent_name": "Hermes Relay",
  "token": "worker-auth-token",
  "capabilities": [
    "mcp.register",
    "mcp.unregister",
    "mcp.start",
    "mcp.stop",
    "mcp.restart",
    "mcp.status",
    "mcp.logs",
    "mcp.tools",
    "mcp.invoke"
  ]
}
```

### heartbeat (worker -> server)

```json
{
  "type": "heartbeat",
  "agent_id": "relay-32",
  "timestamp": "2026-05-26T12:00:00Z"
}
```

### task (server -> worker)

```json
{
  "type": "task",
  "task_id": "task-123",
  "action": "mcp.invoke",
  "payload": {
    "name": "filesystem",
    "tool_name": "read_file",
    "arguments": { "path": "/workspace/test.txt" }
  }
}
```

### task_result (worker -> server)

```json
{
  "type": "task_result",
  "task_id": "task-123",
  "ok": true,
  "data": { "content": "hello" },
  "error": null
}
```

## 支持的 task action

### mcp.register

```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
  "cwd": "/workspace",
  "env": {},
  "auto_start": true
}
```

### mcp.unregister

```json
{ "name": "filesystem" }
```

### mcp.start / mcp.stop / mcp.restart

```json
{ "name": "filesystem" }
```

### mcp.status

```json
{}
```

或

```json
{ "name": "filesystem" }
```

### mcp.logs

```json
{ "name": "filesystem", "lines": 100 }
```

### mcp.tools

```json
{ "name": "filesystem" }
```

### mcp.invoke

```json
{
  "name": "filesystem",
  "tool_name": "read_file",
  "arguments": { "path": "/workspace/test.txt" }
}
```

## 使用自定义 MCP

### 在 32 号机上手动配置（推荐）

通过本地 Admin API 直接在 32 号机注册：

```bash
curl -X POST http://127.0.0.1:8766/mcp/register \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "chrome-devtools",
    "command": "chrome-devtools-mcp",
    "args": [],
    "auto_start": false
  }'
curl -X POST http://127.0.0.1:8766/mcp/chrome-devtools/start
```

或者直接写入 `servers.json`（Relay 启动时 `auto_start: true` 自动拉起）。

### 通过 33 号机（Gateway）远程配置

```python
# 注册
await tools.relay_mcp_register(
    name="chrome-devtools",
    command="chrome-devtools-mcp",
    args=[],
    auto_start=False,
)

# 启动
await tools.relay_mcp_start("chrome-devtools")

# 查看可用工具
print(await tools.relay_mcp_tools("chrome-devtools"))

# 调用工具
result = await tools.relay_mcp_invoke(
    server="chrome-devtools",
    tool="some_tool",
    arguments={"url": "http://localhost:9222"},
)
```

## MCP servers.json

`registry_file` 指向持久化配置文件，结构如下（见 `servers.example.json`）：

```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
      "cwd": "/workspace",
      "env": {},
      "auto_start": true
    },
    {
      "name": "chrome-devtools",
      "command": "chrome-devtools-mcp",
      "args": [],
      "cwd": null,
      "env": {},
      "auto_start": false
    }
  ]
}
```

> **环境变量说明**：`env` 字段中的变量会**合并**到继承的系统环境（包括 `PATH`），而非替换整个环境。

## stdio MCP 工具发现与调用

`mcp.start` 后，Relay 使用 `stdio` 与 MCP server 建立最小 JSON-RPC 通道：

1. `initialize`
2. `notifications/initialized`
3. `tools/list`（对应 `mcp.tools`）
4. `tools/call`（对应 `mcp.invoke`）

同时采集日志：

- `{log_dir}/{name}.stdout.log`
- `{log_dir}/{name}.stderr.log`

## 本地联调（可选）

**方式 1：用 mock_ws_server 模拟 33**

启动 mock server（模拟 Gateway）：

```bash
python mock_ws_server.py
```

再启动 Relay worker（32 端）：

```bash
python -m hermes_relay --config config.json
```

mock server 会打印 `register`、`heartbeat` 与 `task_result`，便于联调。

**方式 2：完整两端联调**

在 33 启动 Gateway：

```bash
python -m hermes_gateway --config gateway_config.json
```

在 32 启动 Relay：

```bash
python -m hermes_relay --config config.json
```

## 测试

```bash
python -m unittest discover -s tests -v
```
