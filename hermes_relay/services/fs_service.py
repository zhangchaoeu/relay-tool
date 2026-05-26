from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from hermes_relay.security import ensure_path_allowed


class FileService:
    def __init__(self, allowed_roots: list[Path]):
        self.allowed_roots = allowed_roots

    async def list_dir(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target = ensure_path_allowed(payload["path"], self.allowed_roots)
        if not target.exists():
            raise FileNotFoundError(str(target))
        if not target.is_dir():
            raise NotADirectoryError(str(target))

        entries: List[Dict[str, Any]] = []
        for item in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            entries.append(
                {
                    "name": item.name,
                    "path": str(item),
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else None,
                }
            )
        return {"entries": entries}

    async def read_file(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target = ensure_path_allowed(payload["path"], self.allowed_roots)
        if not target.exists():
            raise FileNotFoundError(str(target))
        content = target.read_text(encoding=payload.get("encoding", "utf-8"))
        return {"content": content}

    async def write_file(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target = ensure_path_allowed(payload["path"], self.allowed_roots)
        target.parent.mkdir(parents=True, exist_ok=True)

        content = payload.get("content", "")
        target.write_text(content, encoding=payload.get("encoding", "utf-8"))
        return {"path": str(target), "bytes_written": len(content.encode(payload.get("encoding", "utf-8")))}
