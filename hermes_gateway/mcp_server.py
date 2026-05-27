"""MCP Server for Hermes Gateway.

Exposes relay worker tools via the Model Context Protocol using the
Streamable HTTP transport (JSON-RPC over HTTP POST/Response).

Client POSTs JSON-RPC requests to a single URL and receives the JSON-RPC
response directly in the HTTP response body. Supports multiple simultaneous
MCP client connections (stateless per-request, with optional session tracking).
"""

from __future__ import annotations

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


async def _dispatch(gateway: Gateway, method: str | None, params: dict[str, Any]) -> Any:
    """Dispatch a JSON-RPC method call and return the result."""
    if method == "initialize":
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": SERVER_CAPABILITIES,
            "serverInfo": SERVER_INFO,
        }
    elif method == "tools/list":
        return {"tools": TOOL_DEFINITIONS}
    elif method == "tools/call":
        return await _call_tool(gateway, params)
    elif method == "ping":
        return {}
    else:
        raise ValueError(f"Unsupported method: {method}")


async def _call_tool(gateway: Gateway, params: dict[str, Any]) -> dict[str, Any]:
    """Execute a tool call and return the MCP content response."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})

    if tool_name == "relay_mcp_invoke":
        data = await gateway.call_worker(
            "mcp.invoke",
            {
                "name": arguments["server"],
                "tool_name": arguments["tool"],
                "arguments": arguments.get("arguments", {}),
            },
        )
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    elif tool_name == "relay_mcp_tools":
        data = await gateway.call_worker("mcp.tools", {"name": arguments["server"]})
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    elif tool_name == "relay_mcp_start":
        data = await gateway.call_worker("mcp.start", {"name": arguments["server"]})
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    elif tool_name == "relay_mcp_stop":
        data = await gateway.call_worker("mcp.stop", {"name": arguments["server"]})
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    elif tool_name == "relay_mcp_status":
        payload: dict[str, Any] = {}
        if "server" in arguments and arguments["server"]:
            payload["name"] = arguments["server"]
        data = await gateway.call_worker("mcp.status", payload)
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
        data = await gateway.call_worker("mcp.register", payload)
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    elif tool_name == "relay_mcp_unregister":
        data = await gateway.call_worker("mcp.unregister", {"name": arguments["server"]})
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    elif tool_name == "relay_mcp_logs":
        data = await gateway.call_worker(
            "mcp.logs",
            {"name": arguments["server"], "lines": arguments.get("lines", 100)},
        )
        return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]}

    else:
        raise ValueError(f"Unknown tool: {tool_name}")


async def _handle_jsonrpc_message(
    gateway: Gateway, msg: dict[str, Any]
) -> dict[str, Any] | None:
    """Process a single JSON-RPC message and return the response (or None for notifications)."""
    method = msg.get("method")
    request_id = msg.get("id")
    params = msg.get("params", {})

    # Notifications (no id) – no response
    if request_id is None:
        if method == "notifications/initialized":
            logger.debug("Client sent initialized notification")
        return None

    try:
        result = await _dispatch(gateway, method, params)
        return _make_response(request_id, result)
    except WorkerOfflineError as exc:
        return _make_error(request_id, -32000, str(exc))
    except TimeoutError as exc:
        return _make_error(request_id, -32000, str(exc))
    except Exception as exc:
        logger.exception("Error handling method=%s", method)
        return _make_error(request_id, -32603, str(exc))


class GatewayMCPServer:
    """Streamable HTTP MCP server that supports multiple concurrent clients.

    Transport: Streamable HTTP – client POSTs JSON-RPC to a single endpoint
    and receives the JSON-RPC response in the HTTP response body.

    Endpoint: POST /mcp
    Optional session tracking via Mcp-Session-Id header.
    """

    MCP_PATH = "/mcp"

    def __init__(self, gateway: Gateway, host: str = "127.0.0.1", port: int = 8808) -> None:
        self.gateway = gateway
        self.host = host
        self.port = port
        self._app = web.Application()
        self._app.router.add_post(self.MCP_PATH, self._handle_request)
        self._app.router.add_get(self.MCP_PATH, self._handle_get)
        self._app.router.add_delete(self.MCP_PATH, self._handle_delete)

    async def start(self) -> web.AppRunner:
        """Start the MCP HTTP server. Returns the runner for lifecycle management."""
        runner = web.AppRunner(self._app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        logger.info("MCP server (streamable-http) listening on http://%s:%d%s", self.host, self.port, self.MCP_PATH)
        return runner

    async def _handle_request(self, request: web.Request) -> web.Response:
        """POST /mcp – handle JSON-RPC request and return response in body."""
        # Validate content type
        content_type = request.content_type
        if content_type not in ("application/json",):
            return web.json_response(
                _make_error(None, -32700, "Content-Type must be application/json"),
                status=400,
            )

        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response(
                _make_error(None, -32700, "Parse error: invalid JSON"),
                status=400,
            )

        # Generate or echo session id
        session_id = request.headers.get("Mcp-Session-Id") or str(uuid.uuid4())

        # Handle batch request
        if isinstance(body, list):
            responses = []
            for msg in body:
                resp = await _handle_jsonrpc_message(self.gateway, msg)
                if resp is not None:
                    responses.append(resp)
            if not responses:
                # All were notifications
                return web.Response(
                    status=202,
                    headers={"Mcp-Session-Id": session_id},
                )
            return web.json_response(
                responses,
                headers={"Mcp-Session-Id": session_id},
            )

        # Single request
        response = await _handle_jsonrpc_message(self.gateway, body)
        if response is None:
            # Notification – no response body
            return web.Response(
                status=202,
                headers={"Mcp-Session-Id": session_id},
            )

        return web.json_response(
            response,
            headers={"Mcp-Session-Id": session_id},
        )

    async def _handle_get(self, request: web.Request) -> web.Response:
        """GET /mcp – not used in stateless mode, return method not allowed."""
        return web.Response(status=405, text="Method Not Allowed. Use POST.")

    async def _handle_delete(self, request: web.Request) -> web.Response:
        """DELETE /mcp – session termination (no-op in stateless mode)."""
        return web.Response(status=200, text="OK")
