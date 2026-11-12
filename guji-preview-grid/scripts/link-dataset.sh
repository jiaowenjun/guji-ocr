#!/usr/bin/env bash
# 生成 guji-preview-grid 的 kangxi-gold 数据集本地访问层：
#   public/dataset/index.json    页清单（来自 kangxi-gold/manifest.json）
#   public/dataset/annotations -> <repo>/kangxi-gold/annotations（.gj 文本）
#   public/dataset/images      -> manifest.images_dir（WD-2T 扫描图）
# public/dataset/ 已 gitignore；重跑安全（ln -sfn 覆盖、index.json 重写）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$ROOT/kangxi-gold/manifest.json"
DEST="$PROJECT/public/dataset"

[ -f "$MANIFEST" ] || { echo "✗ 缺少 $MANIFEST" >&2; exit 1; }

mkdir -p "$DEST"

IMAGES_DIR="$(python3 - "$MANIFEST" "$DEST/index.json" <<'PY'
import json, sys

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
pages = [
    {
        "page": p["page"],
        "image": p["image"],
        "gj": p["annotations"]["gj"],
        "width": p["width"],
        "height": p["height"],
        "status": p.get("status", "first"),
    }
    for p in manifest["pages"]
]
out = {"source": "kangxi-gold", "images_dir": manifest["images_dir"], "pages": pages}
with open(sys.argv[2], "w", encoding="utf-8") as f:
    f.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
print(f"index.json：{len(pages)} 页（{pages[0]['page']}–{pages[-1]['page']}）", file=sys.stderr)
print(manifest["images_dir"])
PY
)"

[ -d "$IMAGES_DIR" ] || { echo "✗ 图片目录不可用（外置盘未挂载？）：$IMAGES_DIR" >&2; exit 1; }

ln -sfn "$ROOT/kangxi-gold/annotations" "$DEST/annotations"
ln -sfn "$IMAGES_DIR" "$DEST/images"
echo "✓ $DEST"
echo "  annotations -> $ROOT/kangxi-gold/annotations"
echo "  images      -> $IMAGES_DIR"
