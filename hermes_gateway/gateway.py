from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from hermes_gateway.config import GatewayConfig
from hermes_gateway.state import WorkerState

logger = logging.getLogger(__name__)


class WorkerOfflineError(RuntimeError):
    """Raised when a task is dispatched but the worker is not connected."""


class Gateway:
    """Core gateway: holds a single WorkerState and exposes call_worker()."""

    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.state = WorkerState()

    # ------------------------------------------------------------------
    # Core call
    # ------------------------------------------------------------------

    async def call_worker(
        self,
        action: str,
        payload: dict[str, Any],
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Send a task to the worker and await the task_result.

        Args:
            action:  Action name (e.g. "fs.read").
            payload: Action-specific payload dict.
            timeout: Override timeout in seconds; falls back to config default.

        Returns:
            The ``data`` portion of the task_result (dict).

        Raises:
            WorkerOfflineError: Worker is not connected.
            TimeoutError:       Worker did not respond within *timeout* seconds.
            RuntimeError:       Worker returned ok=False.
        """
        if not self.state.online or self.state.connection is None:
            raise WorkerOfflineError("Worker windows-32 is not connected")

        task_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self.state.add_pending(task_id, future)

        task_msg = {
            "type": "task",
            "task_id": task_id,
            "action": action,
            "payload": payload,
        }
        await self.state.connection.send(json.dumps(task_msg))

        effective_timeout = timeout if timeout is not None else self.config.default_task_timeout_seconds
        try:
            result = await asyncio.wait_for(asyncio.shield(future), timeout=effective_timeout)
        except asyncio.TimeoutError:
            self.state._pending.pop(task_id, None)
            raise TimeoutError(f"Task {task_id} ({action}) timed out after {effective_timeout}s")

        if not result.get("ok"):
            raise RuntimeError(f"Task failed: {result.get('error')}")

        return result.get("data") or {}

    # ------------------------------------------------------------------
    # Message handlers (called by the WebSocket server)
    # ------------------------------------------------------------------

    def handle_register(
        self,
        msg: dict[str, Any],
        connection: Any,
    ) -> bool:
        """Validate and store an incoming register message.

        Returns True on success, False if auth fails.
        """
        if msg.get("agent_id") != self.config.worker_agent_id:
            logger.warning(
                "Register rejected: unexpected agent_id=%s", msg.get("agent_id")
            )
            return False
        if msg.get("token") != self.config.worker_token:
            logger.warning("Register rejected: token mismatch for agent_id=%s", msg.get("agent_id"))
            return False

        self.state.register(connection, msg.get("capabilities", []))
        return True

    def handle_heartbeat(self, msg: dict[str, Any]) -> None:
        self.state.record_heartbeat()
        logger.debug("Heartbeat from worker at %s", msg.get("timestamp"))

    def handle_task_result(self, msg: dict[str, Any]) -> None:
        task_id = msg.get("task_id")
        if not task_id:
            logger.warning("Received task_result with no task_id")
            return
        self.state.resolve(task_id, msg)
