#!/usr/bin/env bash
# 生成 guji-preview-grid 的 kangxi-gold 数据集本地访问层：
#   public/dataset/annotations -> <repo>/kangxi-gold/annotations（.gj 文本）
#   public/dataset/images      -> manifest.images_dir（WD-2T 扫描图）
# 爬取字头/词条由本地 API 按需查库，不生成数据快照。
# public/dataset/ 已 gitignore；重跑安全（ln -sfn 覆盖）。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
MANIFEST="$ROOT/kangxi-gold/manifest.json"
DEST="$PROJECT/public/dataset"

[ -f "$MANIFEST" ] || { echo "✗ 缺少 $MANIFEST" >&2; exit 1; }

mkdir -p "$DEST"
# 迁移旧访问层：清单和字形映射现在直接查询本地源。
rm -f "$DEST/index.json" "$DEST/headword-svg.json"

IMAGES_DIR="$(python3 - "$MANIFEST" <<'PYCODE'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    print(json.load(f)["images_dir"])
PYCODE
)"

[ -d "$IMAGES_DIR" ] || { echo "✗ 图片目录不可用（外置盘未挂载？）：$IMAGES_DIR" >&2; exit 1; }

ln -sfn "$ROOT/kangxi-gold/annotations" "$DEST/annotations"
ln -sfn "$IMAGES_DIR" "$DEST/images"

# 字头条缺字兜底：仅连接 SVG 资源目录；身份映射由本地 API 实时解析。
# 映射源：report.json 的 base_char（未编码评估已定身份者）+ font-patches.jsonl
# 的 cp（kKangXi 槽位仲裁后补录/定案者，优先级更高）。目录缺省只告警——
# 字头条退化为系统字体兜底，不影响其余功能。
UNENC="$ROOT/var/unencoded/kangxi-unencoded"
if [ -d "$UNENC/svg" ]; then
  ln -sfn "$UNENC/svg" "$DEST/unencoded-svg"
else
  echo "⚠ 缺 $UNENC/svg——字头条缺字格退化为系统字体" >&2
fi

# 未编码字头格（查询结果 svg 字段直用）：WD-2T 随爬 SVG 缓存，目录布局
# = page_chars.svg 相对路径（0000s/… 千位桶），前端直拼即得，零映射。
# 路径事实源 tools/paths.py；未挂载只告警——未编码格破图回退 □。
HEADSVG="$(python3 -c "import sys; sys.path.insert(0, '$ROOT/tools'); import paths; print(paths.RAW_KANGXI_SVG)")"
if [ -d "$HEADSVG" ]; then
  ln -sfn "$HEADSVG" "$DEST/head-svg"
else
  echo "⚠ 缺 $HEADSVG（外置盘未挂载？）——未编码字头格破图回退 □" >&2
fi

echo "✓ $DEST"
echo "  annotations -> $ROOT/kangxi-gold/annotations"
echo "  images      -> $IMAGES_DIR"
