# Hermes Relay (Windows Worker)

Hermes Relay 是运行在 **Windows 32 号机**上的远程 worker。它不是主聊天 Agent，而是通过 **反向 WebSocket 长连接**主动连接 33 号机，接收任务、执行并回传结果。

## 功能范围

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

## 项目结构

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
config.example.json
servers.example.json
mock_ws_server.py
```

## 安装

```bash
python -m pip install -r requirements.txt
```

## 配置

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

## 启动

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
    }
  ]
}
```

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

启动 mock server：

```bash
python mock_ws_server.py
```

再启动 worker：

```bash
python -m hermes_relay --config config.json
```

mock server 会打印 `register`、`heartbeat` 与 `task_result`，便于联调。

## 测试

```bash
python -m unittest discover -s tests -v
```
