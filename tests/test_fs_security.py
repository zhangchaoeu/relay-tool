from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hermes_relay.security import SecurityError, ensure_path_allowed, normalize_allowed_roots
from hermes_relay.services.fs_service import FileService


class FileSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.allowed = normalize_allowed_roots([str(self.root)])
        self.fs = FileService(self.allowed)

    async def asyncTearDown(self) -> None:
        self.tmp.cleanup()

    async def test_write_read_list_in_allowed_root(self) -> None:
        target = self.root / "a" / "test.txt"
        await self.fs.write_file({"path": str(target), "content": "hello"})

        read = await self.fs.read_file({"path": str(target)})
        listed = await self.fs.list_dir({"path": str(target.parent)})

        self.assertEqual(read["content"], "hello")
        self.assertEqual(len(listed["entries"]), 1)
        self.assertEqual(listed["entries"][0]["name"], "test.txt")

    async def test_path_traversal_is_blocked(self) -> None:
        outside = self.root.parent / "outside.txt"
        with self.assertRaises(SecurityError):
            ensure_path_allowed(str(outside), self.allowed)
