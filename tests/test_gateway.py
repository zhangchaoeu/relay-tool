from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from hermes_gateway.config import GatewayConfig
from hermes_gateway.gateway import Gateway, WorkerOfflineError
from hermes_gateway.state import WorkerState


def _make_config(**kwargs) -> GatewayConfig:
    defaults = dict(
        host="127.0.0.1",
        port=9999,
        worker_agent_id="windows-32",
        worker_token="secret",
        default_task_timeout_seconds=5,
        heartbeat_timeout_seconds=30,
    )
    defaults.update(kwargs)
    return GatewayConfig(**defaults)


class TestGatewayAuth(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = _make_config()
        self.gw = Gateway(self.cfg)
        self.conn = MagicMock()

    def test_register_succeeds_with_correct_credentials(self) -> None:
        ok = self.gw.handle_register(
            {
                "type": "register",
                "agent_id": "windows-32",
                "token": "secret",
                "capabilities": ["fs.list"],
            },
            self.conn,
        )
        self.assertTrue(ok)
        self.assertTrue(self.gw.state.online)

    def test_register_fails_with_wrong_agent_id(self) -> None:
        ok = self.gw.handle_register(
            {"type": "register", "agent_id": "OTHER", "token": "secret"},
            self.conn,
        )
        self.assertFalse(ok)
        self.assertFalse(self.gw.state.online)

    def test_register_fails_with_wrong_token(self) -> None:
        ok = self.gw.handle_register(
            {"type": "register", "agent_id": "windows-32", "token": "WRONG"},
            self.conn,
        )
        self.assertFalse(ok)
        self.assertFalse(self.gw.state.online)


class TestCallWorkerOffline(unittest.IsolatedAsyncioTestCase):
    async def test_raises_when_worker_offline(self) -> None:
        cfg = _make_config()
        gw = Gateway(cfg)
        with self.assertRaises(WorkerOfflineError):
            await gw.call_worker("fs.list", {"path": "."})


class TestCallWorkerTimeout(unittest.IsolatedAsyncioTestCase):
    async def test_raises_timeout_when_no_result(self) -> None:
        cfg = _make_config(default_task_timeout_seconds=1)
        gw = Gateway(cfg)

        # Simulate online worker whose connection never sends a result back.
        fake_conn = AsyncMock()
        gw.state.register(fake_conn, ["fs.list"])

        with self.assertRaises(TimeoutError):
            await gw.call_worker("fs.list", {"path": "."}, timeout=1)


class TestCallWorkerSuccess(unittest.IsolatedAsyncioTestCase):
    async def test_returns_data_on_ok_result(self) -> None:
        cfg = _make_config()
        gw = Gateway(cfg)

        fake_conn = AsyncMock()
        gw.state.register(fake_conn, ["fs.list"])

        # Resolve the future immediately after the task is sent.
        async def _resolve_after_send(*args, **kwargs) -> None:
            raw = args[0]
            msg = json.loads(raw)
            task_id = msg["task_id"]
            # Slightly defer resolution so the future is registered first.
            await asyncio.sleep(0)
            gw.handle_task_result(
                {
                    "type": "task_result",
                    "task_id": task_id,
                    "ok": True,
                    "data": {"entries": []},
                    "error": None,
                }
            )

        fake_conn.send = _resolve_after_send
        result = await gw.call_worker("fs.list", {"path": "."})
        self.assertEqual(result, {"entries": []})


class TestCallWorkerErrorResult(unittest.IsolatedAsyncioTestCase):
    async def test_raises_on_task_error(self) -> None:
        cfg = _make_config()
        gw = Gateway(cfg)

        fake_conn = AsyncMock()
        gw.state.register(fake_conn, ["fs.read"])

        async def _send_error(raw: str) -> None:
            msg = json.loads(raw)
            await asyncio.sleep(0)
            gw.handle_task_result(
                {
                    "type": "task_result",
                    "task_id": msg["task_id"],
                    "ok": False,
                    "data": None,
                    "error": "File not found",
                }
            )

        fake_conn.send = _send_error
        with self.assertRaisesRegex(RuntimeError, "File not found"):
            await gw.call_worker("fs.read", {"path": "D:/missing.txt"})


class TestHeartbeatAndDisconnect(unittest.TestCase):
    def test_heartbeat_updates_timestamp(self) -> None:
        cfg = _make_config()
        gw = Gateway(cfg)
        conn = MagicMock()
        gw.state.register(conn, [])

        before = gw.state.last_heartbeat
        gw.handle_heartbeat({"type": "heartbeat", "timestamp": "2026-05-26T12:00:00Z"})
        after = gw.state.last_heartbeat
        self.assertIsNotNone(after)
        self.assertGreaterEqual(after, before)

    def test_disconnect_clears_state(self) -> None:
        cfg = _make_config()
        gw = Gateway(cfg)
        conn = MagicMock()
        gw.state.register(conn, ["fs.list"])
        gw.state.disconnect()

        self.assertFalse(gw.state.online)
        self.assertIsNone(gw.state.connection)
