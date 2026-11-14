#!/usr/bin/env python3
"""Download a Hugging Face dataset snapshot into a given local directory.

Usage: hf_snapshot.py <repo_id> <target_dir>
"""
import sys

from huggingface_hub import snapshot_download


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    repo_id, target_dir = sys.argv[1], sys.argv[2]
    path = snapshot_download(
        repo_id=repo_id,
        repo_type="dataset",
        local_dir=target_dir,
        max_workers=8,
    )
    print("SNAPSHOT-DONE", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
