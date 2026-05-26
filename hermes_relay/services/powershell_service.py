from __future__ import annotations

import asyncio
from typing import Any, Dict


PREDEFINED_ACTIONS = {
    "whoami": "whoami",
    "hostname": "hostname",
    "ps_version": "$PSVersionTable.PSVersion.ToString()",
}


class PowerShellService:
    def __init__(self, allowlist: list[str]):
        self.allowlist = set(allowlist)

    async def run_safe(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        cmd = self._resolve_command(payload)
        proc = await asyncio.create_subprocess_exec(
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
        }

    def _resolve_command(self, payload: Dict[str, Any]) -> str:
        if "action" in payload:
            action = payload["action"]
            if action not in PREDEFINED_ACTIONS:
                raise PermissionError(f"Unknown action: {action}")
            if action not in self.allowlist:
                raise PermissionError(f"Action not allowed: {action}")
            return PREDEFINED_ACTIONS[action]

        command = payload.get("command")
        if not command:
            raise ValueError("Missing action or command")
        if command not in self.allowlist:
            raise PermissionError("Command not allowlisted")
        return command
