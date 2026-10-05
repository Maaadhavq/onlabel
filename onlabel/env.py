"""Load `.env` into the process environment, once.

Hand-rolled (same as mandate-retry-sequencer's `env.py`): fifteen lines beat a dependency.
Real environment variables always win; a stale file must never replace a key someone
exported on purpose. A missing file is not an error: running with no keys is supported.
"""

from __future__ import annotations

import os
from pathlib import Path

_loaded = False


def load_env(path: Path | str = ".env", *, force: bool = False) -> int:
    """Read `KEY=value` lines into `os.environ`. Returns how many were set."""
    global _loaded
    if _loaded and not force:
        return 0
    _loaded = True
    path = Path(path)
    if not path.exists():
        return 0

    applied = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if not key or not value or os.environ.get(key):
            continue
        os.environ[key] = value
        applied += 1
    return applied
