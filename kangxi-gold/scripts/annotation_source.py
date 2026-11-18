"""Read current manifest .gj sources through the production parser (Node 22.18+)."""
import json
import subprocess
from pathlib import Path

DERIVE = Path(__file__).resolve().parents[2] / "tools/dataset/annotation_source.mjs"


def derive_annotations(root: Path) -> dict[int, dict]:
    result = subprocess.run(
        ["node", str(DERIVE)],
        input=json.dumps({"manifest": str((root / "manifest.json").resolve())}),
        capture_output=True, text=True, check=True,
    )
    return {row["page"]: row for row in json.loads(result.stdout)}
