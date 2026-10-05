"""Fetch labels from DailyMed, parse them, and pin what was fetched in a manifest.

The first fetch of a label resolves its set_id from a DailyMed search; after that the
manifest pins set_id, version and the XML's SHA-256, so a rebuild either reproduces the
same corpus or says exactly which label changed.

    uv run python -m onlabel.data.fetch_labels                 # the walking-skeleton labels
    uv run python -m onlabel.data.fetch_labels --all           # the whole corpus
    uv run python -m onlabel.data.fetch_labels --refresh wegovy
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime

from onlabel.data.corpus import CORPUS, LABELS_DIR, MANIFEST, RAW_DIR, SKELETON, LabelSpec
from onlabel.data.dailymed import DailyMed, SplHit
from onlabel.data.parse_spl import parse_spl


def pick(spec: LabelSpec, hits: list[SplHit]) -> SplHit:
    own = [h for h in hits if spec.manufacturer in h.title.upper()]
    if not own:
        raise LookupError(f"{spec.key}: no DailyMed label from {spec.manufacturer}: {[h.title for h in hits]}")
    # Prefer the label whose title starts with this brand (Ozempic tablets share Rybelsus's).
    branded = [h for h in own if h.title.upper().startswith(spec.query.upper())] or own
    return max(branded, key=lambda h: h.spl_version)


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}


def fetch(spec: LabelSpec, dm: DailyMed, manifest: dict, refresh: bool, reparse: bool = False) -> dict:
    pinned = manifest.get(spec.key)
    if reparse:
        if not pinned:
            raise LookupError(f"{spec.key}: not in the manifest yet; fetch it first")
        raw = RAW_DIR / f"{pinned['set_id']}_v{pinned['version']}.xml"
        xml = raw.read_bytes()
        if hashlib.sha256(xml).hexdigest() != pinned["xml_sha256"]:
            raise ValueError(f"{raw}: does not match the manifest's sha256")
        set_id = pinned["set_id"]
    else:
        if pinned and not refresh:
            set_id = pinned["set_id"]
        else:
            hit = pick(spec, dm.search(spec.query))
            set_id = hit.set_id
            print(f"  {spec.key}: resolved {set_id} ({hit.title[:80]})")
        xml = dm.spl_xml(set_id)
    label = parse_spl(xml)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{set_id}_v{label.version}.xml").write_bytes(xml)
    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    (LABELS_DIR / f"{spec.key}.json").write_text(
        json.dumps(label.to_dict(), indent=1) + "\n", encoding="utf-8", newline="\n"
    )

    entry = {
        "set_id": set_id,
        "version": label.version,
        "effective_time": label.effective_time,
        "products": label.products,
        "generic": label.generic,
        "ingredient": spec.ingredient,
        "role": spec.role,
        "xml_sha256": hashlib.sha256(xml).hexdigest(),
        "n_sections": len(label.sections),
        "fetched_on": datetime.now(UTC).date().isoformat(),
    }
    if pinned and pinned.get("version") != label.version:
        print(f"  {spec.key}: label changed v{pinned.get('version')} -> v{label.version}")
    if label.skipped_codes:
        print(f"  {spec.key}: unrecognised top-level sections {label.skipped_codes}")
    return entry


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("keys", nargs="*", help="corpus keys; default: the walking-skeleton set")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--refresh", action="store_true", help="re-resolve set_ids from a fresh search")
    ap.add_argument("--reparse", action="store_true", help="re-parse the cached XML; no network")
    args = ap.parse_args()

    keys = list(CORPUS) if args.all else (args.keys or SKELETON)
    manifest = load_manifest()
    dm = DailyMed()
    for key in keys:
        entry = fetch(CORPUS[key], dm, manifest, args.refresh, args.reparse)
        manifest[key] = entry
        print(f"  {key:10} v{entry['version']:<3} {entry['effective_time']}  {entry['n_sections']:3} sections  "
              f"{', '.join(entry['products'])}")
    MANIFEST.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
