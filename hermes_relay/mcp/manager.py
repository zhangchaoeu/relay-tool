from __future__ import annotations

from collections import deque
import json
from pathlib import Path
from typing import Any, Dict

import psutil
from pydantic import ValidationError

from hermes_relay.config import MCPServerConfig, RelayConfig
from hermes_relay.mcp.protocol import StdioMCPClient


class MCPManager:
    def __init__(self, config: RelayConfig):
        self.config = config
        self.registry_path = Path(config.registry_file).resolve()
        self.log_dir = Path(config.log_dir).resolve()
        self._running: dict[str, StdioMCPClient] = {}

    def list_registered(self) -> dict[str, MCPServerConfig]:
        if not self.registry_path.exists():
            return {}
        data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        result: dict[str, MCPServerConfig] = {}
        for row in data.get("servers", []):
            cfg = MCPServerConfig.model_validate(row)
            result[cfg.name] = cfg
        return result

    def _save_registered(self, servers: dict[str, MCPServerConfig]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"servers": [s.model_dump() for s in servers.values()]}
        self.registry_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    async def unregister(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload["name"]
        if name in self._running:
            await self.stop({"name": name})
        servers = self.list_registered()
        if name not in servers:
            raise KeyError(f"MCP server not registered: {name}")
        del servers[name]
        self._save_registered(servers)
        return {"unregistered": name}

    async def register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            cfg = MCPServerConfig.model_validate(payload)
        except ValidationError as e:
            raise ValueError(str(e)) from e

        servers = self.list_registered()
        servers[cfg.name] = cfg
        self._save_registered(servers)
        return {"registered": cfg.name}

    async def start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload["name"]
        if name in self._running:
            return {"name": name, "status": "running"}

        cfg = self.list_registered().get(name)
        if not cfg:
            raise KeyError(f"MCP server not found: {name}")

        client = StdioMCPClient(
            name=cfg.name,
            command=cfg.command,
            args=cfg.args,
            cwd=cfg.cwd,
            env=cfg.env,
            log_dir=self.log_dir,
            request_timeout_seconds=self.config.mcp_request_timeout_seconds,
        )
        await client.start()
        self._running[name] = client
        return {"name": name, "status": "running"}

    async def stop(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload["name"]
        client = self._running.pop(name, None)
        if not client:
            return {"name": name, "status": "stopped"}
        await client.stop()
        return {"name": name, "status": "stopped"}

    async def restart(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload["name"]
        await self.stop({"name": name})
        return await self.start({"name": name})

    async def status(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload.get("name")
        registered = self.list_registered()
        if name:
            runtime = self._running.get(name)
            proc_info: Dict[str, Any] | None = None
            if runtime and runtime.process and runtime.process.pid:
                try:
                    process = psutil.Process(runtime.process.pid)
                    with process.oneshot():
                        proc_info = {
                            "pid": process.pid,
                            "status": process.status(),
                            "rss_bytes": process.memory_info().rss,
                            "cpu_percent": process.cpu_percent(interval=0.0),
                        }
                except psutil.Error:
                    proc_info = None
            return {
                "name": name,
                "registered": name in registered,
                "running": name in self._running,
                "process": proc_info,
            }
        servers = []
        for server_name, cfg in registered.items():
            runtime = self._running.get(server_name)
            server_proc_info: Dict[str, Any] | None = None
            if runtime and runtime.process and runtime.process.pid:
                try:
                    process = psutil.Process(runtime.process.pid)
                    with process.oneshot():
                        server_proc_info = {
                            "pid": process.pid,
                            "status": process.status(),
                            "rss_bytes": process.memory_info().rss,
                        }
                except psutil.Error:
                    server_proc_info = None
            servers.append(
                {
                    "name": server_name,
                    "registered": True,
                    "running": server_name in self._running,
                    "auto_start": cfg.auto_start,
                    "process": server_proc_info,
                }
            )
        return {"servers": servers}

    async def logs(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload["name"]
        lines = int(payload.get("lines", 100))
        result = {}
        for stream in ("stdout", "stderr"):
            path = self.log_dir / f"{name}.{stream}.log"
            if not path.exists():
                result[stream] = ""
                continue
            tail = deque(maxlen=lines)
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    tail.append(line.rstrip("\n"))
            result[stream] = "\n".join(tail)
        return result

    async def tools(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload["name"]
        client = self._running.get(name)
        if not client:
            raise RuntimeError("Server is not running")
        return await client.list_tools()

    async def invoke(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        name = payload["name"]
        tool_name = payload["tool_name"]
        arguments = payload.get("arguments", {})
        client = self._running.get(name)
        if not client:
            raise RuntimeError("Server is not running")
        return await client.invoke_tool(tool_name, arguments)

    async def auto_start(self) -> None:
        for name, cfg in self.list_registered().items():
            if cfg.auto_start and name not in self._running:
                await self.start({"name": name})
