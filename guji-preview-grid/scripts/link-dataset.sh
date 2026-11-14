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

# 字头条缺字兜底：站点字头缩略图 SVG + 字符→文件名映射（headword-svg.json）。
# 映射源：report.json 的 base_char（未编码评估已定身份者）+ font-patches.jsonl
# 的 cp（kKangXi 槽位仲裁后补录/定案者，优先级更高）。目录缺省只告警——
# 字头条退化为系统字体兜底，不影响其余功能。
UNENC="$ROOT/var/unencoded/kangxi-unencoded"
if [ -d "$UNENC/svg" ]; then
  ln -sfn "$UNENC/svg" "$DEST/unencoded-svg"
else
  echo "⚠ 缺 $UNENC/svg——字头条缺字格退化为系统字体" >&2
fi
python3 - "$UNENC" "$DEST/headword-svg.json" <<'PY'
import json, os, sys

src, out = sys.argv[1], sys.argv[2]
mapping: dict[str, str] = {}

def put(char: str, svg_path: str) -> None:
    name = os.path.basename(svg_path)
    if char and name:
        mapping.setdefault(char, name)  # 同字符多处扫描取首见；补录记录后置覆盖

report = os.path.join(src, "report.json")
if os.path.isfile(report):
    for item in json.load(open(report, encoding="utf-8")).get("items", []):
        put(item.get("base_char") or "", item.get("svg") or "")

# 补录/仲裁记录后处理，直接覆盖（身份定案优先于评估首见）
patches = os.path.join(src, "font-patches.jsonl")
if os.path.isfile(patches):
    for line in open(patches, encoding="utf-8"):
        rec = json.loads(line)
        for r in rec.get("results", []):
            cp = r.get("cp", "")
            if cp.startswith("U+"):
                try:
                    char = chr(int(cp[2:], 16))
                except ValueError:
                    continue
                name = os.path.basename(rec.get("svg") or "")
                if name:
                    mapping[char] = name

with open(out, "w", encoding="utf-8") as f:
    f.write(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
print(f"headword-svg.json：{len(mapping)} 字符 → SVG", file=sys.stderr)
PY

echo "✓ $DEST"
echo "  annotations -> $ROOT/kangxi-gold/annotations"
echo "  images      -> $IMAGES_DIR"
