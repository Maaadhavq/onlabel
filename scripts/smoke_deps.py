"""Import every dependency and say which ones the OS refuses to load.

Windows Smart App Control blocks some native DLLs (pyarrow and lxml so far). The failure
is an ImportError that looks like a code bug, so this script runs first on any new machine
or environment and names the culprit.

    uv run python scripts/smoke_deps.py            # runtime + dev
    uv run python scripts/smoke_deps.py --data     # also the offline data tooling
"""

from __future__ import annotations

import argparse
import importlib
import platform
import sys

RUNTIME = ["fastapi", "uvicorn", "pydantic", "httpx", "openai", "numpy", "onnxruntime", "tokenizers"]
DEV = ["pytest"]
DATA = ["pymupdf", "huggingface_hub"]
# Must NOT be importable: once installed they break unrelated imports on this machine.
FORBIDDEN = ["pyarrow", "lxml"]


def probe(name: str) -> tuple[str, str]:
    try:
        mod = importlib.import_module(name)
    except ModuleNotFoundError:
        return "missing", ""
    except ImportError as exc:
        blocked = "Application Control" in str(exc) or "blocked" in str(exc)
        return ("BLOCKED" if blocked else "error"), str(exc).splitlines()[0][:120]
    return "ok", str(getattr(mod, "__version__", getattr(mod, "VersionBundle", "")) or "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", action="store_true", help="also check the offline data tooling")
    args = ap.parse_args()

    print(f"python {sys.version.split()[0]} on {platform.system()} {platform.release()}")
    groups = {"runtime": RUNTIME, "dev": DEV}
    if args.data:
        groups["data"] = DATA

    failed = 0
    for group, names in groups.items():
        for name in names:
            status, detail = probe(name)
            failed += status != "ok"
            print(f"  [{group:7}] {name:16} {status:8} {detail}")

    for name in FORBIDDEN:
        status, detail = probe(name)
        if status != "missing":
            failed += 1
            print(f"  [forbid ] {name:16} INSTALLED ({status}) - uninstall it: {detail}")

    if "onnxruntime" not in {n for n in RUNTIME if probe(n)[0] != "ok"}:
        import onnxruntime as ort

        print(f"  onnxruntime providers: {ort.get_available_providers()}")

    print("FAIL" if failed else "OK", f"({failed} problem(s))")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
