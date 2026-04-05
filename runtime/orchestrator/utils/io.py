"""Atomic file write utilities.

Provides crash-safe file writes using the tmp-file + os.replace() pattern.
All state-bearing JSON files should use these functions instead of direct open().
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Union


def atomic_write_json(
    path: Union[str, Path],
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    """Write JSON data atomically using tmp + replace.

    The write is crash-safe: if the process dies mid-write, the original
    file remains intact (or doesn't exist yet).

    Args:
        path: Target file path.
        data: JSON-serializable data.
        indent: JSON indent level.
        ensure_ascii: Whether to escape non-ASCII characters.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(p.parent),
        prefix=f".{p.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(p))
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_text(
    path: Union[str, Path],
    content: str,
    *,
    encoding: str = "utf-8",
) -> None:
    """Write text content atomically using tmp + replace.

    Args:
        path: Target file path.
        content: Text content to write.
        encoding: File encoding.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(p.parent),
        prefix=f".{p.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(p))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
