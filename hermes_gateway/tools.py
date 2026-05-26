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

    async def windows_mcp_register(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        auto_start: bool = False,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Register a new MCP server on the worker.

        Use this to register an MCP server that is already installed (e.g. via
        ``npm install -g chrome-devtools-mcp``) or a fully custom script.  After
        registration call :meth:`windows_mcp_start` to launch it.

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
            environment.  You do *not* need to include ``PATH``; the worker
            always inherits the parent environment.
        auto_start:
            Whether the worker should start this server automatically on boot.
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

    async def windows_mcp_unregister(
        self, server: str, timeout: int | None = None
    ) -> dict[str, Any]:
        """Unregister an MCP server on the worker (stops it first if running)."""
        return await self._gw.call_worker("mcp.unregister", {"name": server}, timeout=timeout)

    async def windows_mcp_install(
        self,
        ecosystem: str,
        package: str,
        version: str | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Install an MCP package on the worker (requires package to be allowlisted).

        Parameters
        ----------
        ecosystem:
            ``"npm"`` or ``"pip"``.
        package:
            Package name, e.g. ``"@modelcontextprotocol/server-filesystem"``.
        version:
            Optional pinned version string.
        """
        payload: dict[str, Any] = {"ecosystem": ecosystem, "package": package}
        if version is not None:
            payload["version"] = version
        return await self._gw.call_worker("mcp.install", payload, timeout=timeout)

    async def windows_mcp_logs(
        self,
        server: str,
        lines: int = 100,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        """Retrieve recent log output from an MCP server on the worker."""
        return await self._gw.call_worker(
            "mcp.logs", {"name": server, "lines": lines}, timeout=timeout
        )
