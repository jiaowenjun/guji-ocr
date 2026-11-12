#!/usr/bin/env bash
# 软链本机已安装的刻本字体到 public/fonts/，作为 @font-face url() 兜底源。
#
# 背景：Safari/WebKit 对 font-family 本机字体与 @font-face local() 的匹配
# 在部分用户字体上不可靠（康熙傳承版/中华书局宋体均中招），Chrome 正常。
# url() 直接加载字体文件在任何浏览器都成立；Chrome 仍优先 local() 秒出。
# 字体文件不入 git（.gitignore 已忽略 public/fonts/），缺失时给出安装提示。
set -euo pipefail

PROJECT="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$PROJECT/public/fonts"

map_font() { # $1=稳定文件名 $2=查找模式 $3=说明
  local stable="$1" pattern="$2" note="$3" src
  src="$(find "$HOME/Library/Fonts" /Library/Fonts -maxdepth 1 -iname "$pattern" 2>/dev/null | head -1 || true)"
  if [ -z "$src" ]; then
    echo "✗ 未找到：$note（模式 $pattern）" >&2
    MISSING=1
    return
  fi
  ln -sfn "$src" "$DEST/$stable.ttf"
  echo "  $stable.ttf -> $src"
}

mkdir -p "$DEST"
MISSING=0
echo "链接刻本字体到 ${DEST}："
map_font guji-large 'KX_*.ttf' '康熙傳承版 KangXiZiDian.com'
map_font guji-plane0 '中华书局宋体00平面*.TTF' '中华书局宋体00平面（BMP 基本区）'
map_font guji-plane2 '中华书局宋体02平面*.TTF' '中华书局宋体02平面（扩展 B 区）'
map_font guji-planef '中华书局宋体15平面*.TTF' '中华书局宋体15平面（扩展 C+）'

if [ "$MISSING" -eq 1 ]; then
  echo "请先安装缺失字体（下载方式见 README 字体说明），或手动把 .ttf 放入 $DEST" >&2
  exit 1
fi
echo "✓ 完成：@font-face 优先 local()（Chrome），失败经 url() 加载以上文件（Safari）"
