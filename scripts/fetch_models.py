"""Download the pinned ONNX artefacts into models/hf/ (gitignored; the Dockerfile runs this).

Plain HTTPS against the Hub's resolve endpoint, so the runtime image does not need
huggingface_hub. The CDN drops long transfers now and then (a Docker build lost the
connection at 12 of 34 MB), so downloads resume with HTTP Range requests and every file
is checked against its pinned SHA-256.

    uv run python scripts/fetch_models.py
"""

from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onlabel.models import SHIPPED, OnnxArtefact

HUB = "https://huggingface.co"
ATTEMPTS = 8


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path, expected_sha: str) -> None:
    part = dest.with_name(dest.name + ".part")
    for attempt in range(1, ATTEMPTS + 1):
        have = part.stat().st_size if part.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        try:
            with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
                if r.status_code == 416:  # already complete
                    break
                r.raise_for_status()
                mode = "ab" if r.status_code == 206 else "wb"  # 200 means the server ignored Range
                with open(part, mode) as fh:
                    fh.writelines(r.iter_bytes(1 << 20))
            break
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            got = part.stat().st_size if part.exists() else 0
            print(f"    attempt {attempt}/{ATTEMPTS} stopped at {got / 1e6:.1f} MB: {type(exc).__name__}")
            if attempt == ATTEMPTS:
                raise
            time.sleep(min(2**attempt, 30))

    actual = sha256_of(part)
    if actual != expected_sha:
        part.unlink()
        raise RuntimeError(f"{dest}: sha256 {actual} != pinned {expected_sha}")
    part.replace(dest)


def fetch(art: OnnxArtefact) -> None:
    art.local_dir.mkdir(parents=True, exist_ok=True)
    for remote, local, sha in art.files():
        if local.exists() and sha256_of(local) == sha:
            print(f"  have {local}")
            continue
        download(f"{HUB}/{art.repo}/resolve/{art.revision}/{remote}", local, sha)
        print(f"  got  {local} ({local.stat().st_size / 1e6:.1f} MB, sha256 ok)")


def main() -> int:
    for art in SHIPPED:
        print(f"{art.key} @ {art.revision[:8]}")
        fetch(art)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
