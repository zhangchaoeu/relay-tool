from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)


class MCPError(RuntimeError):
    pass


@dataclass
class StdioMCPClient:
    name: str
    command: str
    args: list[str]
    cwd: str | None
    env: dict[str, str]
    log_dir: Path
    request_timeout_seconds: int = 30
    process: asyncio.subprocess.Process | None = None
    _next_id: int = 1
    _pending: dict[int, asyncio.Future] = field(default_factory=dict)
    _read_task: asyncio.Task | None = None
    _stderr_task: asyncio.Task | None = None
    _write_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def start(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            cwd=self.cwd,
            env=self.env or None,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._read_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._stderr_loop())
        await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hermes-relay", "version": "0.1.0"},
            },
        )
        await self.notify("notifications/initialized", {})

    async def stop(self) -> None:
        if not self.process:
            return

        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()

        for task in (self._read_task, self._stderr_task):
            if task:
                task.cancel()

        self.process = None

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.process or not self.process.stdin:
            raise MCPError("MCP server is not running")

        request_id = self._next_id
        self._next_id += 1

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future

        msg = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        await self._write_message(msg)
        result = await asyncio.wait_for(future, timeout=self.request_timeout_seconds)
        if "error" in result and result["error"] is not None:
            raise MCPError(str(result["error"]))
        return result.get("result", {})

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        msg = {"jsonrpc": "2.0", "method": method, "params": params}
        await self._write_message(msg)

    async def list_tools(self) -> dict[str, Any]:
        return await self.request("tools/list", {})

    async def invoke_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await self.request("tools/call", {"name": name, "arguments": arguments})

    async def _write_message(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise MCPError("MCP server is not running")

        payload = json.dumps(message).encode("utf-8")
        wire = f"Content-Length: {len(payload)}\r\n\r\n".encode("utf-8") + payload

        async with self._write_lock:
            self.process.stdin.write(wire)
            await self.process.stdin.drain()

        self._append_log("stdout", f"-> {json.dumps(message, ensure_ascii=False)}")

    async def _read_loop(self) -> None:
        assert self.process and self.process.stdout
        reader = self.process.stdout

        while True:
            headers: dict[str, str] = {}
            while True:
                line = await reader.readline()
                if not line:
                    return
                if line in (b"\r\n", b"\n"):
                    break
                decoded = line.decode("utf-8")
                if ":" not in decoded:
                    self._append_log("stderr", f"Malformed MCP header: {decoded.rstrip()}")
                    continue
                key, value = decoded.split(":", 1)
                headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            if content_length <= 0:
                continue
            body = await reader.readexactly(content_length)
            raw = body.decode("utf-8")
            self._append_log("stdout", f"<- {raw}")
            msg = json.loads(raw)
            if "id" in msg and msg["id"] in self._pending:
                self._pending.pop(msg["id"]).set_result(msg)

    async def _stderr_loop(self) -> None:
        assert self.process and self.process.stderr
        reader = self.process.stderr
        while True:
            line = await reader.readline()
            if not line:
                return
            self._append_log("stderr", line.decode("utf-8", errors="replace").rstrip())

    def _append_log(self, stream: str, content: str) -> None:
        path = self.log_dir / f"{self.name}.{stream}.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(content + "\n")
