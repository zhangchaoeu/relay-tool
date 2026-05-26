from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict

from hermes_relay.mcp.manager import MCPManager

logger = logging.getLogger(__name__)


class TaskDispatcher:
    def __init__(self, mcp: MCPManager):
        self.handlers: Dict[str, Callable[[Dict[str, Any]], Any]] = {
            "mcp.register": mcp.register,
            "mcp.unregister": mcp.unregister,
            "mcp.start": mcp.start,
            "mcp.stop": mcp.stop,
            "mcp.restart": mcp.restart,
            "mcp.status": mcp.status,
            "mcp.logs": mcp.logs,
            "mcp.tools": mcp.tools,
            "mcp.invoke": mcp.invoke,
        }

    @property
    def capabilities(self) -> list[str]:
        return list(self.handlers.keys())

    async def dispatch(self, task: Dict[str, Any]) -> Dict[str, Any]:
        task_id = task.get("task_id")
        action = task.get("action")
        payload = task.get("payload", {})

        if action not in self.handlers:
            return {
                "type": "task_result",
                "task_id": task_id,
                "ok": False,
                "data": None,
                "error": f"Unsupported action: {action}",
            }

        try:
            data = await self.handlers[action](payload)
            return {
                "type": "task_result",
                "task_id": task_id,
                "ok": True,
                "data": data,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("Task execution failed for action=%s task_id=%s", action, task_id)
            return {
                "type": "task_result",
                "task_id": task_id,
                "ok": False,
                "data": None,
                "error": str(exc),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
