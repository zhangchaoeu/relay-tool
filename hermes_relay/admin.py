"""Local HTTP admin API for manual MCP configuration on the relay side.

Endpoints
---------
GET  /mcp/status              — list all registered MCP servers and their status
GET  /mcp/{name}/status       — status of a specific server
POST /mcp/register            — register a new MCP server (JSON body: MCPServerConfig fields)
DELETE /mcp/{name}            — unregister (and stop) a server
POST /mcp/{name}/start        — start a server
POST /mcp/{name}/stop         — stop a server
POST /mcp/{name}/restart      — restart a server
GET  /mcp/{name}/logs         — tail logs (?lines=100)
GET  /mcp/{name}/tools        — list available MCP tools (server must be running)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Dict, Tuple
from urllib.parse import parse_qs, urlparse

from hermes_relay.mcp.manager import MCPManager

logger = logging.getLogger(__name__)

_ROUTE_STATUS_ALL = re.compile(r"^/mcp/status$")
_ROUTE_REGISTER = re.compile(r"^/mcp/register$")
_ROUTE_SERVER = re.compile(r"^/mcp/(?P<name>[^/]+)$")
_ROUTE_SERVER_ACTION = re.compile(r"^/mcp/(?P<name>[^/]+)/(?P<action>status|start|stop|restart|logs|tools)$")


def _json_response(status: str, body: Any) -> bytes:
    body_bytes = json.dumps(body, ensure_ascii=False).encode()
    header = (
        f"HTTP/1.1 {status}\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body_bytes)}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    return header.encode() + body_bytes


async def _read_request(reader: asyncio.StreamReader) -> Tuple[str, str, Dict[str, str], bytes]:
    """Read and parse a minimal HTTP/1.1 request. Returns (method, path, headers, body)."""
    raw_line = await reader.readline()
    if not raw_line:
        raise ConnectionResetError("Empty request")
    parts = raw_line.decode("latin-1").strip().split(" ", 2)
    if len(parts) < 2:
        raise ValueError("Malformed request line")
    method, raw_path = parts[0].upper(), parts[1]

    headers: Dict[str, str] = {}
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
        if b":" in line:
            key, _, value = line.decode("latin-1").partition(":")
            headers[key.strip().lower()] = value.strip()

    body = b""
    if "content-length" in headers:
        length = int(headers["content-length"])
        if length > 0:
            body = await reader.readexactly(length)

    return method, raw_path, headers, body


class AdminServer:
    """Asyncio-based HTTP admin server for local MCP management on the relay side."""

    def __init__(self, mcp: MCPManager, host: str = "127.0.0.1", port: int = 8766) -> None:
        self.mcp = mcp
        self.host = host
        self.port = port

    async def start(self) -> asyncio.Server:
        server = await asyncio.start_server(self._handle, self.host, self.port)
        addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
        logger.info("Admin HTTP server listening on %s", addrs)
        return server

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            method, raw_path, _headers, body = await _read_request(reader)
            parsed = urlparse(raw_path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)

            response = await self._route(method, path, query, body)
            writer.write(response)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Admin request error from %s: %s", peer, exc)
            writer.write(_json_response("400 Bad Request", {"error": str(exc)}))
        finally:
            try:
                await writer.drain()
            except Exception:  # noqa: BLE001
                pass
            writer.close()

    async def _route(self, method: str, path: str, query: Dict[str, list], body: bytes) -> bytes:
        # GET /mcp/status
        if method == "GET" and _ROUTE_STATUS_ALL.match(path):
            data = await self.mcp.status({})
            return _json_response("200 OK", data)

        # POST /mcp/register
        if method == "POST" and _ROUTE_REGISTER.match(path):
            payload = json.loads(body) if body else {}
            data = await self.mcp.register(payload)
            return _json_response("200 OK", data)

        # Routes with a server name
        m = _ROUTE_SERVER_ACTION.match(path)
        if m:
            name = m.group("name")
            action = m.group("action")

            if method == "GET" and action == "status":
                data = await self.mcp.status({"name": name})
                return _json_response("200 OK", data)

            if method == "POST" and action == "start":
                data = await self.mcp.start({"name": name})
                return _json_response("200 OK", data)

            if method == "POST" and action == "stop":
                data = await self.mcp.stop({"name": name})
                return _json_response("200 OK", data)

            if method == "POST" and action == "restart":
                data = await self.mcp.restart({"name": name})
                return _json_response("200 OK", data)

            if method == "GET" and action == "logs":
                lines = int(query.get("lines", ["100"])[0])
                data = await self.mcp.logs({"name": name, "lines": lines})
                return _json_response("200 OK", data)

            if method == "GET" and action == "tools":
                data = await self.mcp.tools({"name": name})
                return _json_response("200 OK", data)

        # DELETE /mcp/{name}
        m2 = _ROUTE_SERVER.match(path)
        if m2 and method == "DELETE":
            name = m2.group("name")
            data = await self.mcp.unregister({"name": name})
            return _json_response("200 OK", data)

        return _json_response("404 Not Found", {"error": f"No route for {method} {path}"})
