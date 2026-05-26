from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_relay.config import RelayConfig
from hermes_relay.dispatcher import TaskDispatcher
from hermes_relay.mcp.manager import MCPManager
from hermes_relay.security import normalize_allowed_roots
from hermes_relay.services.fs_service import FileService
from hermes_relay.services.powershell_service import PowerShellService


class DispatcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsupported_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = RelayConfig(
                ws_server_url="ws://localhost:9000/ws",
                agent_id="test",
                worker_token="token",
                allowed_file_roots=[tmp],
                powershell_allowlist=["whoami"],
                registry_file=str(Path(tmp) / "servers.json"),
                log_dir=str(Path(tmp) / "logs"),
            )
            dispatcher = TaskDispatcher(
                fs=FileService(normalize_allowed_roots(cfg.allowed_file_roots)),
                powershell=PowerShellService(cfg.powershell_allowlist),
                mcp=MCPManager(cfg),
            )
            result = await dispatcher.dispatch({"task_id": "1", "action": "unknown", "payload": {}})
            self.assertFalse(result["ok"])
            self.assertIn("Unsupported action", result["error"])
