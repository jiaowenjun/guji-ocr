#!/usr/bin/env python3
"""Build a download manifest for datasets/ as JSON for the evidence directory.

Usage: make_manifest.py <datasets_root>
Prints JSON to stdout. Records per-dataset files, sizes and SHA-256.
"""
import hashlib
import json
import sys
from datetime import date
from pathlib import Path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    root = Path(sys.argv[1])
    manifest = {
        "recorded_at": str(date.today()),
        "purpose": "Local download manifest of datasets named in docs/research; sizes and SHA-256 as evidence of obtained versions.",
        "root": str(root),
        "datasets": {},
    }
    for ds_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        entries = []
        for f in sorted(ds_dir.rglob("*")):
            if f.is_file() and ".cache" not in f.parts:
                entries.append(
                    {
                        "path": str(f.relative_to(ds_dir)),
                        "size_bytes": f.stat().st_size,
                        "sha256": sha256_of(f),
                    }
                )
        manifest["datasets"][ds_dir.name] = {
            "files": len(entries),
            "total_bytes": sum(e["size_bytes"] for e in entries),
            "items": entries,
        }
    json.dump(manifest, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
