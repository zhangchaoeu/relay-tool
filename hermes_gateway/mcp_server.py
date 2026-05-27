"""MCP Server for Hermes Gateway.

Exposes relay worker tools via the Model Context Protocol (JSON-RPC over SSE/HTTP)
so that Hermes agents can load this as a standard MCP tool server.

Supports multiple simultaneous MCP client connections.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from aiohttp import web

from hermes_gateway.gateway import Gateway, WorkerOfflineError

logger = logging.getLogger(__name__)

# JSON-RPC helpers
JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2024-11-05"

SERVER_INFO = {
    "name": "hermes-gateway-mcp",
    "version": "0.1.0",
}

SERVER_CAPABILITIES = {
    "tools": {"listChanged": False},
}

# Tool definitions exposed to MCP clients
TOOL_DEFINITIONS = [
    {
        "name": "relay_mcp_invoke",
        "description": "Invoke a tool on a remote MCP server managed by the relay worker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of the MCP server on the relay worker.",
                },
                "tool": {
                    "type": "string",
                    "description": "Tool name to invoke on the remote MCP server.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments to pass to the tool.",
                    "default": {},
                },
            },
            "required": ["server", "tool"],
        },
    },
    {
        "name": "relay_mcp_tools",
        "description": "List available tools on a remote MCP server managed by the relay worker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of the MCP server on the relay worker.",
                },
            },
            "required": ["server"],
        },
    },
    {
        "name": "relay_mcp_start",
        "description": "Start a registered MCP server on the relay worker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of the MCP server to start.",
                },
            },
            "required": ["server"],
        },
    },
    {
        "name": "relay_mcp_stop",
        "description": "Stop a running MCP server on the relay worker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of the MCP server to stop.",
                },
            },
            "required": ["server"],
        },
    },
    {
        "name": "relay_mcp_status",
        "description": "Query status of MCP servers on the relay worker. If no server name is given, returns status of all servers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of a specific MCP server (optional).",
                },
            },
        },
    },
    {
        "name": "relay_mcp_register",
        "description": "Register a new MCP server on the relay worker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Logical server name.",
                },
                "command": {
                    "type": "string",
                    "description": "Executable command to run.",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Command-line arguments.",
                    "default": [],
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (optional).",
                },
                "env": {
                    "type": "object",
                    "description": "Additional environment variables.",
                    "default": {},
                },
                "auto_start": {
                    "type": "boolean",
                    "description": "Whether to auto-start on boot.",
                    "default": False,
                },
            },
            "required": ["name", "command"],
        },
    },
    {
        "name": "relay_mcp_unregister",
        "description": "Unregister an MCP server on the relay worker (stops it first if running).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of the MCP server to unregister.",
                },
            },
            "required": ["server"],
        },
    },
    {
        "name": "relay_mcp_logs",
        "description": "Retrieve recent log output from an MCP server on the relay worker.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {
                    "type": "string",
                    "description": "Name of the MCP server.",
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of recent lines to retrieve.",
                    "default": 100,
                },
            },
            "required": ["server"],
        },
    },
]


def _make_response(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}


def _make_error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


class MCPSession:
    """Represents a single MCP client session (SSE connection)."""

    def __init__(self, session_id: str, gateway: Gateway) -> None:
        self.session_id = session_id
        self.gateway = gateway
        self.initialized = False
        self._queue: asyncio.Queue[str] = asyncio.Queue()

    def send_event(self, data: dict[str, Any]) -> None:
        """Queue an SSE event for this session."""
        self._queue.put_nowait(json.dumps(data, ensure_ascii=False))

    async def event_stream(self):
        """Async generator yielding SSE-formatted events."""
        while True:
            data = await self._queue.get()
            yield f"data: {data}\n\n"

    async def handle_message(self, msg: dict[str, Any]) -> None:
        """Process a JSON-RPC request from the MCP client."""
        method = msg.get("method")
        request_id = msg.get("id")
        params = msg.get("params", {})

        # Notifications (no id) – just acknowledge
        if request_id is None:
            if method == "notifications/initialized":
                logger.debug("Session %s: client sent initialized notification", self.session_id)
            return

        try:
            result = await self._dispatch(method, params)
            self.send_event(_make_response(request_id, result))
        except WorkerOfflineError as exc:
            self.send_event(_make_error(request_id, -32000, str(exc)))
        except TimeoutError as exc:
            self.send_event(_make_error(request_id, -32000, str(exc)))
        except Exception as exc:
            logger.exception("Session %s: error handling method=%s", self.session_id, method)
            self.send_event(_make_error(request_id, -32603, str(exc)))

    async def _dispatch(self, method: str | None, params: dict[str, Any]) -> Any:
        if method == "initialize":
            self.initialized = True
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": SERVER_CAPABILITIES,
                "serverInfo": SERVER_INFO,
            }
        elif method == "tools/list":
            return {"tools": TOOL_DEFINITIONS}
        elif method == "tools/call":
            return await self._call_tool(params)
        elif method == "ping":
            return {}
        else:
            raise ValueError(f"Unsupported method: {method}")

    async def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name == "relay_mcp_invoke":
            data = await self.gateway.call_worker(
                "mcp.invoke",
                {
                    "name": arguments["server"],
                    "tool_name": arguments["tool"],
                    "arguments": arguments.get("arguments", {}),
                },
            )
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        elif tool_name == "relay_mcp_tools":
            data = await self.gateway.call_worker("mcp.tools", {"name": arguments["server"]})
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        elif tool_name == "relay_mcp_start":
            data = await self.gateway.call_worker("mcp.start", {"name": arguments["server"]})
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        elif tool_name == "relay_mcp_stop":
            data = await self.gateway.call_worker("mcp.stop", {"name": arguments["server"]})
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        elif tool_name == "relay_mcp_status":
            payload: dict[str, Any] = {}
            if "server" in arguments and arguments["server"]:
                payload["name"] = arguments["server"]
            data = await self.gateway.call_worker("mcp.status", payload)
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        elif tool_name == "relay_mcp_register":
            payload = {
                "name": arguments["name"],
                "command": arguments["command"],
                "args": arguments.get("args", []),
                "env": arguments.get("env", {}),
                "auto_start": arguments.get("auto_start", False),
            }
            if "cwd" in arguments and arguments["cwd"]:
                payload["cwd"] = arguments["cwd"]
            data = await self.gateway.call_worker("mcp.register", payload)
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        elif tool_name == "relay_mcp_unregister":
            data = await self.gateway.call_worker("mcp.unregister", {"name": arguments["server"]})
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        elif tool_name == "relay_mcp_logs":
            data = await self.gateway.call_worker(
                "mcp.logs",
                {"name": arguments["server"], "lines": arguments.get("lines", 100)},
            )
            return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

        else:
            raise ValueError(f"Unknown tool: {tool_name}")


class GatewayMCPServer:
    """HTTP/SSE-based MCP server that supports multiple concurrent client sessions.

    Transport: Streamable HTTP (SSE for server->client, POST for client->server).
    Each client gets a unique session via the SSE endpoint and sends requests via POST.
    """

    SSE_PATH = "/sse"
    MESSAGES_PATH = "/messages"

    def __init__(self, gateway: Gateway, host: str = "127.0.0.1", port: int = 8808) -> None:
        self.gateway = gateway
        self.host = host
        self.port = port
        self._sessions: dict[str, MCPSession] = {}
        self._app = web.Application()
        self._app.router.add_get(self.SSE_PATH, self._handle_sse)
        self._app.router.add_post(self.MESSAGES_PATH, self._handle_messages)

    async def start(self) -> web.AppRunner:
        """Start the MCP HTTP server. Returns the runner for lifecycle management."""
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info("MCP server listening on http://%s:%d", self.host, self.port)
        return runner

    async def _handle_sse(self, request: web.Request) -> web.StreamResponse:
        """SSE endpoint: establishes a new MCP session and streams events."""
        session_id = str(uuid.uuid4())
        session = MCPSession(session_id, self.gateway)
        self._sessions[session_id] = session

        response = web.StreamResponse(
            status=200,
            reason="OK",
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Session-Id": session_id,
            },
        )
        await response.prepare(request)

        # Send endpoint event so client knows where to POST
        endpoint_event = f"event: endpoint\ndata: {self.MESSAGES_PATH}?session_id={session_id}\n\n"
        await response.write(endpoint_event.encode("utf-8"))

        logger.info("MCP session %s started", session_id)

        try:
            async for event_data in session.event_stream():
                await response.write(event_data.encode("utf-8"))
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        finally:
            self._sessions.pop(session_id, None)
            logger.info("MCP session %s closed", session_id)

        return response

    async def _handle_messages(self, request: web.Request) -> web.Response:
        """POST endpoint: receives JSON-RPC messages from MCP clients."""
        session_id = request.query.get("session_id")
        if not session_id or session_id not in self._sessions:
            return web.json_response(
                {"error": "Invalid or missing session_id"},
                status=400,
            )

        session = self._sessions[session_id]

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        # Handle batch or single message
        if isinstance(body, list):
            for msg in body:
                await session.handle_message(msg)
        else:
            await session.handle_message(body)

        return web.Response(status=202, text="Accepted")
