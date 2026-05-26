# Hermes Relay & Gateway

本仓库包含两个组件，共同构成**反向 WebSocket 远程调用系统**：

| 组件 | 运行主机 | 职责 |
|------|----------|------|
| **Hermes Relay**（`hermes_relay/`） | Windows 32 号机 | 主动连接 33，执行任务并回传结果 |
| **Hermes Gateway**（`hermes_gateway/`） | Linux/Mac 33 号机 | 接受 32 的连接，暴露 `call_worker()` API 供 Hermes 调用 |

> English: The repo contains a reverse-WebSocket pair. The Relay (host 32) dials out to the Gateway (host 33). Hermes on host 33 calls `call_worker()` or the convenience `HermesTools` wrappers to dispatch tasks.

---

## Hermes Gateway（运行在 33 上）

### 功能

- 接受 `windows-32` 的 WebSocket 反向连接
- 校验 `agent_id` 和 `token`
- 维护单 worker 在线状态、最近心跳、capabilities
- 核心方法 `call_worker(action, payload, timeout)`
  - 自动生成 `task_id`（uuid4）
  - 发送 `task` 消息
  - 等待对应 `task_result`（支持超时）
  - worker 不在线时抛 `WorkerOfflineError`
- `HermesTools` 封装：`windows_fs_read/write/list`、`windows_powershell_safe`、`windows_mcp_invoke` 等

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
- `worker_agent_id`：预期的 worker ID（`"windows-32"`）
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
result = await gateway.call_worker("fs.list", {"path": "D:/agent_workspace"})

# 或使用工具封装
entries = await tools.windows_fs_list("D:/agent_workspace")
content = await tools.windows_fs_read("D:/agent_workspace/test.txt")
await tools.windows_fs_write("D:/agent_workspace/out.txt", "hello")
whoami = await tools.windows_powershell_safe(action="whoami")
result  = await tools.windows_mcp_invoke("filesystem", "read_file", {"path": "D:/test.txt"})
```

### call_worker 错误处理

| 异常 | 原因 |
|------|------|
| `WorkerOfflineError` | worker 未连接 |
| `TimeoutError` | 任务超时未返回 |
| `RuntimeError` | worker 返回 `ok=False` |

---

## Hermes Relay（运行在 32 上）

Hermes Relay 是运行在 **Windows 32 号机**上的远程 worker。它不是主聊天 Agent，而是通过 **反向 WebSocket 长连接**主动连接 33 号机，接收任务、执行并回传结果。

> English: Hermes Relay is a Windows worker running on host 32. It actively dials host 33 via WebSocket, receives remote tasks, executes them locally, and sends task results back.

## 功能范围（Relay）
- WebSocket worker
  - 启动后主动连接 `ws_server_url`
  - 发送 `register`
  - 定期发送 `heartbeat`
  - 接收 `task` 并返回 `task_result`
  - 自动重连
- 本地能力
  - `fs.list`
  - `fs.read`
  - `fs.write`
  - `powershell.safe`
- MCP 管理能力
  - `mcp.install`
  - `mcp.register`
  - `mcp.unregister`
  - `mcp.start`
  - `mcp.stop`
  - `mcp.restart`
  - `mcp.status`
  - `mcp.logs`
  - `mcp.tools`
  - `mcp.invoke`

> Hermes Relay 不内置网页抓取/浏览器自动化能力；网页能力应通过专门的 MCP server 提供。

## 技术栈

- Python 3.11+
- asyncio
- websockets
- pydantic
- psutil
- subprocess

## 项目结构（Relay）

```text
hermes_relay/
  __main__.py                # 入口
  config.py                  # 配置模型与加载
  security.py                # 路径安全校验
  dispatcher.py              # task action 分发
  worker.py                  # WebSocket 长连接 worker
  services/
    fs_service.py            # fs.list/read/write
    powershell_service.py    # powershell.safe
  mcp/
    manager.py               # MCP 注册、托管、状态、工具调用
    protocol.py              # stdio MCP 最小客户端实现
tests/
  test_fs_security.py
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

- `ws_server_url`
- `agent_id`
- `agent_name`
- `worker_token`
- `heartbeat_interval_seconds`
- `reconnect_interval_seconds`
- `mcp_request_timeout_seconds`
- `allowed_file_roots`
- `powershell_allowlist`
- `allowed_npm_packages`
- `allowed_pip_packages`
- `registry_file`
- `log_dir`

### 文件访问安全

`fs.*` 操作仅允许访问 `allowed_file_roots` 下的路径。若路径越界（目录穿越或非允许根目录），任务会失败。

### PowerShell 安全

`powershell.safe` 只允许：

- allowlist 中的预定义 action（如 `whoami`、`hostname`、`ps_version`）
- 或 allowlist 中精确匹配的命令字符串

不支持任意命令透传。

## 启动（Relay）

```bash
python -m hermes_relay --config config.json
```

## 消息协议

### register (worker -> server)

```json
{
  "type": "register",
  "agent_id": "windows-32",
  "agent_name": "Hermes Relay",
  "token": "worker-auth-token",
  "capabilities": [
    "fs.list",
    "fs.read",
    "fs.write",
    "powershell.safe",
    "mcp.install",
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
  "agent_id": "windows-32",
  "timestamp": "2026-05-26T12:00:00Z"
}
```

### task (server -> worker)

```json
{
  "type": "task",
  "task_id": "task-123",
  "action": "fs.read",
  "payload": {
    "path": "D:\\agent_workspace\\test.txt"
  }
}
```

### task_result (worker -> server)

```json
{
  "type": "task_result",
  "task_id": "task-123",
  "ok": true,
  "data": {
    "content": "hello"
  },
  "error": null
}
```

## 支持的 task action

### 1) fs.list

```json
{
  "path": "D:/agent_workspace"
}
```

### 2) fs.read

```json
{
  "path": "D:/agent_workspace/test.txt",
  "encoding": "utf-8"
}
```

### 3) fs.write

```json
{
  "path": "D:/agent_workspace/test.txt",
  "content": "hello",
  "encoding": "utf-8"
}
```

### 4) powershell.safe

使用预定义 action：

```json
{
  "action": "whoami"
}
```

使用 allowlist 精确命令：

```json
{
  "command": "Get-Process"
}
```

### 5) MCP 管理

- `mcp.install`

```json
{ "ecosystem": "npm", "package": "@modelcontextprotocol/server-filesystem" }
```

- `mcp.register`

```json
{
  "name": "filesystem",
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:/agent_workspace"],
  "cwd": "D:/agent_workspace",
  "env": {},
  "auto_start": true
}
```

- `mcp.unregister`

```json
{ "name": "filesystem" }
```

- `mcp.start` / `mcp.stop` / `mcp.restart`

```json
{ "name": "filesystem" }
```

- `mcp.status`

```json
{}
```

或

```json
{ "name": "filesystem" }
```

- `mcp.logs`

```json
{ "name": "filesystem", "lines": 100 }
```

- `mcp.tools`

```json
{ "name": "filesystem" }
```

- `mcp.invoke`

```json
{
  "name": "filesystem",
  "tool_name": "read_file",
  "arguments": { "path": "D:/agent_workspace/test.txt" }
}
```

## 使用第三方 / 自定义 MCP

### 全局安装的 npm MCP（如 chrome-devtools-mcp）

在 **32 号机** 上先用 npm 全局安装：

```bash
npm install -g chrome-devtools-mcp
```

然后在 **33 号机**（Gateway / Hermes 侧）注册并启动：

```python
# 注册
await tools.windows_mcp_register(
    name="chrome-devtools",
    command="chrome-devtools-mcp",  # 全局 npm bin，PATH 自动继承
    args=[],
    auto_start=False,
)

# 启动
await tools.windows_mcp_start("chrome-devtools")

# 查看可用工具
print(await tools.windows_mcp_tools("chrome-devtools"))

# 调用工具
result = await tools.windows_mcp_invoke(
    server="chrome-devtools",
    tool="some_tool",
    arguments={"url": "http://localhost:9222"},
)
```

或者直接写入 `servers.json`（Relay 启动时 `auto_start: true` 自动拉起）：

```json
{
  "name": "chrome-devtools",
  "command": "chrome-devtools-mcp",
  "args": [],
  "env": {},
  "auto_start": true
}
```

### 自定义脚本 MCP

任意可执行文件（Node.js、Python、二进制……）均可注册，`env` 中的变量会**追加**到继承的系统环境，不会覆盖 `PATH`：

```python
await tools.windows_mcp_register(
    name="my-custom-mcp",
    command="node",
    args=["D:/my_scripts/custom_mcp_server.js"],
    cwd="D:/my_scripts",
    env={"MY_API_KEY": "secret"},  # 仅追加，不替换 PATH
    auto_start=False,
)
await tools.windows_mcp_start("my-custom-mcp")
```

### 注销服务

```python
await tools.windows_mcp_unregister("my-custom-mcp")  # 先自动 stop，再从注册表删除
```

## MCP servers.json

`registry_file` 指向持久化配置文件，结构如下（见 `servers.example.json`）：

```json
{
  "servers": [
    {
      "name": "filesystem",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:/agent_workspace"],
      "cwd": "D:/agent_workspace",
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
    },
    {
      "name": "my-custom-mcp",
      "command": "node",
      "args": ["D:/my_scripts/custom_mcp_server.js"],
      "cwd": "D:/my_scripts",
      "env": { "MY_API_KEY": "your-api-key-here" },
      "auto_start": false
    }
  ]
}
```

> **环境变量说明**：`env` 字段中的变量会**合并**到继承的系统环境（包括 `PATH`），而非替换整个环境。因此全局安装的 npm 可执行文件无需额外配置 `PATH`。

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

再启动 Relay worker（windows-32 端）：

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
