"""Tests for the Gateway MCP Server (Streamable HTTP transport)."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from hermes_gateway.config import GatewayConfig
from hermes_gateway.gateway import Gateway
from hermes_gateway.mcp_server import (
    GatewayMCPServer,
    TOOL_DEFINITIONS,
    _make_response,
    _make_error,
    _handle_jsonrpc_message,
)


class TestHandleJsonrpcMessage(unittest.IsolatedAsyncioTestCase):
    """Test JSON-RPC message handling."""

    def setUp(self):
        config = GatewayConfig(worker_token="test-token")
        self.gateway = Gateway(config)

    async def test_initialize(self):
        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        result = await _handle_jsonrpc_message(self.gateway, msg)
        self.assertEqual(result["id"], 1)
        self.assertIn("protocolVersion", result["result"])
        self.assertIn("serverInfo", result["result"])

    async def test_tools_list(self):
        msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        result = await _handle_jsonrpc_message(self.gateway, msg)
        self.assertEqual(result["id"], 2)
        self.assertEqual(result["result"]["tools"], TOOL_DEFINITIONS)

    async def test_ping(self):
        msg = {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}}
        result = await _handle_jsonrpc_message(self.gateway, msg)
        self.assertEqual(result["id"], 3)
        self.assertEqual(result["result"], {})

    async def test_notification_returns_none(self):
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        result = await _handle_jsonrpc_message(self.gateway, msg)
        self.assertIsNone(result)

    async def test_call_tool_worker_offline(self):
        msg = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "relay_mcp_tools",
                "arguments": {"server": "test-server"},
            },
        }
        result = await _handle_jsonrpc_message(self.gateway, msg)
        self.assertEqual(result["id"], 4)
        self.assertIn("error", result)
        self.assertIn("not connected", result["error"]["message"])

    async def test_call_tool_invoke_success(self):
        self.gateway.call_worker = AsyncMock(return_value={"result": "ok"})
        msg = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "relay_mcp_invoke",
                "arguments": {
                    "server": "filesystem",
                    "tool": "read_file",
                    "arguments": {"path": "/tmp/test.txt"},
                },
            },
        }
        result = await _handle_jsonrpc_message(self.gateway, msg)
        self.assertEqual(result["id"], 5)
        self.assertIn("content", result["result"])
        self.gateway.call_worker.assert_called_once_with(
            "mcp.invoke",
            {"name": "filesystem", "tool_name": "read_file", "arguments": {"path": "/tmp/test.txt"}},
        )

    async def test_unsupported_method(self):
        msg = {"jsonrpc": "2.0", "id": 6, "method": "unknown/method", "params": {}}
        result = await _handle_jsonrpc_message(self.gateway, msg)
        self.assertEqual(result["id"], 6)
        self.assertIn("error", result)


class TestGatewayMCPServerInit(unittest.TestCase):
    """Test GatewayMCPServer initialization."""

    def test_creates_with_defaults(self):
        config = GatewayConfig(worker_token="test-token")
        gateway = Gateway(config)
        mcp_server = GatewayMCPServer(gateway)
        self.assertEqual(mcp_server.host, "127.0.0.1")
        self.assertEqual(mcp_server.port, 8808)

    def test_creates_with_custom_host_port(self):
        config = GatewayConfig(worker_token="test-token")
        gateway = Gateway(config)
        mcp_server = GatewayMCPServer(gateway, host="0.0.0.0", port=9000)
        self.assertEqual(mcp_server.host, "0.0.0.0")
        self.assertEqual(mcp_server.port, 9000)


class TestGatewayMCPServerHTTP(AioHTTPTestCase):
    """Integration test for the Streamable HTTP endpoint."""

    async def get_application(self):
        config = GatewayConfig(worker_token="test-token")
        self.gateway = Gateway(config)
        self.mcp_server = GatewayMCPServer(self.gateway)
        return self.mcp_server._app

    @unittest_run_loop
    async def test_post_initialize(self):
        resp = await self.client.request(
            "POST",
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["id"], 1)
        self.assertIn("protocolVersion", body["result"])
        # Should have session header
        self.assertIn("Mcp-Session-Id", resp.headers)

    @unittest_run_loop
    async def test_post_notification_returns_202(self):
        resp = await self.client.request(
            "POST",
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        )
        self.assertEqual(resp.status, 202)

    @unittest_run_loop
    async def test_post_batch(self):
        resp = await self.client.request(
            "POST",
            "/mcp",
            json=[
                {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            ],
        )
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(len(body), 2)

    @unittest_run_loop
    async def test_get_returns_405(self):
        resp = await self.client.request("GET", "/mcp")
        self.assertEqual(resp.status, 405)

    @unittest_run_loop
    async def test_delete_returns_200(self):
        resp = await self.client.request("DELETE", "/mcp")
        self.assertEqual(resp.status, 200)

    @unittest_run_loop
    async def test_invalid_json_returns_400(self):
        resp = await self.client.request(
            "POST",
            "/mcp",
            data=b"not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)


class TestHelpers(unittest.TestCase):
    """Test JSON-RPC helper functions."""

    def test_make_response(self):
        r = _make_response(1, {"tools": []})
        self.assertEqual(r["jsonrpc"], "2.0")
        self.assertEqual(r["id"], 1)
        self.assertEqual(r["result"], {"tools": []})

    def test_make_error(self):
        r = _make_error(2, -32600, "Invalid Request")
        self.assertEqual(r["jsonrpc"], "2.0")
        self.assertEqual(r["id"], 2)
        self.assertEqual(r["error"]["code"], -32600)
        self.assertEqual(r["error"]["message"], "Invalid Request")

    def test_make_error_with_data(self):
        r = _make_error(3, -32603, "Internal error", data={"detail": "oops"})
        self.assertEqual(r["error"]["data"], {"detail": "oops"})


if __name__ == "__main__":
    unittest.main()
