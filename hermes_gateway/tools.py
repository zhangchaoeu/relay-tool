from __future__ import annotations

from typing import Any

from hermes_gateway.gateway import Gateway


class HermesTools:
    """Ready-to-use wrapper functions for Hermes to call the remote relay worker.

    Each method maps directly to a worker action and returns the raw data dict
    from the task_result.  All network/timeout errors propagate to the caller.
    """

    def __init__(self, gateway: Gateway) -> None:
        self._gw = gateway

    # ------------------------------------------------------------------
    # MCP
    # ------------------------------------------------------------------

    async def relay_mcp_invoke(
        self,
        server: str,
        tool: str,
        arguments: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Invoke a tool on a remote MCP server managed by the relay worker."""
        return await self._gw.call_worker(
            "mcp.invoke",
            {"name": server, "tool_name": tool, "arguments": arguments or {}},
            timeout=timeout,
        )

    async def relay_mcp_tools(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """List available tools on a remote MCP server."""
        return await self._gw.call_worker("mcp.tools", {"name": server}, timeout=timeout)

    async def relay_mcp_start(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Start a registered MCP server on the relay worker."""
        return await self._gw.call_worker("mcp.start", {"name": server}, timeout=timeout)

    async def relay_mcp_stop(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Stop a running MCP server on the relay worker."""
        return await self._gw.call_worker("mcp.stop", {"name": server}, timeout=timeout)

    async def relay_mcp_status(
        self, server: str | None = None, timeout: int | None = None
    ) -> dict[str, Any]:
        """Query MCP server status on the relay worker."""
        payload: dict[str, Any] = {}
        if server is not None:
            payload["name"] = server
        return await self._gw.call_worker("mcp.status", payload, timeout=timeout)

    async def relay_mcp_register(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        auto_start: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Register a new MCP server on the relay worker.

        After registration call :meth:`relay_mcp_start` to launch it.

        Parameters
        ----------
        name:
            Logical server name used in subsequent start/stop/invoke calls.
        command:
            Executable to run, e.g. ``"chrome-devtools-mcp"`` or ``"npx"``.
        args:
            Command-line arguments to pass to *command*.
        cwd:
            Working directory for the subprocess (optional).
        env:
            Additional environment variables merged on top of the inherited
            environment.
        auto_start:
            Whether the relay worker should start this server automatically on boot.
        """
        payload: dict[str, Any] = {
            "name": name,
            "command": command,
            "args": args or [],
            "env": env or {},
            "auto_start": auto_start,
        }
        if cwd is not None:
            payload["cwd"] = cwd
        return await self._gw.call_worker("mcp.register", payload, timeout=timeout)

    async def relay_mcp_unregister(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Unregister an MCP server on the relay worker (stops it first if running)."""
        return await self._gw.call_worker("mcp.unregister", {"name": server}, timeout=timeout)

    async def relay_mcp_logs(
        self,
        server: str,
        lines: int = 100,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve recent log output from an MCP server on the relay worker."""
        return await self._gw.call_worker(
            "mcp.logs", {"name": server, "lines": lines}, timeout=timeout
        )
