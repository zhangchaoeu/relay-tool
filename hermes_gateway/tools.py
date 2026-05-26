from __future__ import annotations

from typing import Any

from hermes_gateway.gateway import Gateway


class HermesTools:
    """Ready-to-use wrapper functions for Hermes to call the remote worker.

    Each method maps directly to a worker action and returns the raw data dict
    from the task_result.  All network/timeout errors propagate to the caller.
    """

    def __init__(self, gateway: Gateway) -> None:
        self._gw = gateway

    # ------------------------------------------------------------------
    # File-system
    # ------------------------------------------------------------------

    async def windows_fs_list(self, path: str, timeout: int | None = None) -> dict[str, Any]:
        """List directory entries on the remote Windows machine."""
        return await self._gw.call_worker("fs.list", {"path": path}, timeout=timeout)

    async def windows_fs_read(
        self,
        path: str,
        encoding: str = "utf-8",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Read a file on the remote Windows machine."""
        return await self._gw.call_worker(
            "fs.read", {"path": path, "encoding": encoding}, timeout=timeout
        )

    async def windows_fs_write(
        self,
        path: str,
        content: str,
        encoding: str = "utf-8",
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Write content to a file on the remote Windows machine."""
        return await self._gw.call_worker(
            "fs.write",
            {"path": path, "content": content, "encoding": encoding},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # PowerShell
    # ------------------------------------------------------------------

    async def windows_powershell_safe(
        self,
        action: str | None = None,
        command: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Run an allowlisted PowerShell action or command.

        Pass *action* for predefined actions (whoami, hostname, ps_version) or
        *command* for an exact allowlisted command string.
        """
        payload: dict[str, Any] = {}
        if action is not None:
            payload["action"] = action
        if command is not None:
            payload["command"] = command
        return await self._gw.call_worker("powershell.safe", payload, timeout=timeout)

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------

    async def windows_mcp_invoke(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool on a remote MCP server managed by the worker."""
        return await self._gw.call_worker(
            "mcp.invoke",
            {"name": server, "tool_name": tool, "arguments": arguments or {}},
            timeout=timeout,
        )

    async def windows_mcp_tools(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """List available tools on a remote MCP server."""
        return await self._gw.call_worker("mcp.tools", {"name": server}, timeout=timeout)

    async def windows_mcp_start(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Start a registered MCP server on the worker."""
        return await self._gw.call_worker("mcp.start", {"name": server}, timeout=timeout)

    async def windows_mcp_stop(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Stop a running MCP server on the worker."""
        return await self._gw.call_worker("mcp.stop", {"name": server}, timeout=timeout)

    async def windows_mcp_status(
        self, server: str | None = None, timeout: int | None = None
    ) -> dict[str, Any]:
        """Query MCP server status on the worker."""
        payload: dict[str, Any] = {}
        if server is not None:
            payload["name"] = server
        return await self._gw.call_worker("mcp.status", payload, timeout=timeout)
