#!/usr/bin/env bash
# 生成 guji-preview-grid 的 kangxi-gold 数据集本地访问层：
#   public/dataset/index.json    页清单（来自 kangxi-gold/manifest.json）
#   public/dataset/annotations -> <repo>/kangxi-gold/annotations（.gj 文本）
#   public/dataset/images      -> manifest.images_dir（WD-2T 扫描图）
#   public/dataset/entries.json 爬取库词条全文（字头详情弹窗，码位键）
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

# 字头详情弹窗与字头栏「爬取」段数据源：爬取库（tools/crawl SQLite，与爬取
# 演示页同源）。逐数据集页取 page_chars →
#   entries.json    有码位者取 entries.record_json，按码位键出词条全文
#                   （未编码 k_code 无详情端点，不在表内——前端回退并注明）
#   page-heads.json 逐页原始字头索引（含未编码 K 码项），键为页码字符串
# 库不可用（外置盘未挂载等）写空表并告警，不阻断其余生成步骤。
python3 - "$ROOT" "$DEST/entries.json" "$DEST/page-heads.json" <<'PY'
import json, sys
from pathlib import Path

root, out_records, out_heads = sys.argv[1], sys.argv[2], sys.argv[3]
manifest = json.load(open(Path(root) / "kangxi-gold/manifest.json", encoding="utf-8"))
pages = [p["page"] for p in manifest["pages"]]

KEEP = ("head", "guwen", "juan", "unicode", "radical", "radical_strokes",
        "extra_strokes", "total_strokes", "pinyin", "zhuyin", "cangjie",
        "unihan", "tongwen_edition", "wuying_edition", "text_paragraphs",
        "pua_other")

records: dict[str, dict] = {}
heads_by_page: dict[str, list[dict]] = {}
db = None

def head_item(it: dict) -> dict:
    cp = it.get("codepoint")
    return {"ord": it.get("ord"), "char": it.get("char"),
            "cp": f"{cp:X}" if cp else None, "k_code": it.get("k_code"),
            "svg": it.get("svg"), "entry_no": it.get("entry_no")}

try:
    sys.path.insert(0, str(Path(root) / "tools/crawl"))
    import kangxi_store  # 自带 sys.path 修正（tools/），无需先导入 paths

    if Path(kangxi_store.DEFAULT_DB).is_file():
        store = kangxi_store.KangxiStore()
        db = kangxi_store.DEFAULT_DB
        for page in pages:
            items = store.get_page_chars(page)
            heads_by_page[str(page)] = [head_item(it) for it in items]
            for it in items:
                cp = it.get("codepoint")
                if not cp:
                    continue  # 未编码 k_code：无详情端点
                row = store.get_entry(cp)
                if row and row.get("record_json"):
                    rec = json.loads(row["record_json"])
                    records[f"{cp:X}"] = {k: rec.get(k) for k in KEEP}
except Exception as e:  # noqa: BLE001
    print(f"⚠ 爬取库不可用（{type(e).__name__}: {e}）——entries/page-heads 写空表，前端回退 .gj", file=sys.stderr)

with open(out_records, "w", encoding="utf-8") as f:
    f.write(json.dumps(records, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
with open(out_heads, "w", encoding="utf-8") as f:
    f.write(json.dumps(heads_by_page, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
src = f"爬取库 {db}" if db else "无库（空表）"
n_heads = sum(len(v) for v in heads_by_page.values())
print(f"entries.json：{len(records)} 条词条；page-heads.json：{n_heads} 字头/{len(heads_by_page)} 页（{src}）", file=sys.stderr)
PY

echo "✓ $DEST"
echo "  annotations -> $ROOT/kangxi-gold/annotations"
echo "  images      -> $IMAGES_DIR"
