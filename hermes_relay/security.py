from __future__ import annotations

from pathlib import Path
from typing import Iterable


class SecurityError(ValueError):
    pass


def normalize_allowed_roots(roots: Iterable[str]) -> list[Path]:
    normalized: list[Path] = []
    for root in roots:
        normalized.append(Path(root).expanduser().resolve())
    return normalized


def ensure_path_allowed(path: str | Path, allowed_roots: list[Path]) -> Path:
    if not allowed_roots:
        raise SecurityError("No allowed_file_roots configured")

    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = allowed_roots[0] / candidate

    # strict=False is required so write targets that don't yet exist can still be validated safely.
    resolved = candidate.expanduser().resolve(strict=False)
    for root in allowed_roots:
        try:
            resolved.relative_to(root)
            return resolved
        except ValueError:
            continue

    raise SecurityError(f"Path not allowed: {path}")
