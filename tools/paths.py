#!/usr/bin/env python3
"""统一路径解析：外置盘（WD-2T）与仓库本地 var/ 的唯一事实源。

规范见 docs/data-storage.md。要点：
- 外置盘根可用环境变量 GUJI_WD_ROOT 覆盖（默认 /Volumes/WD-2T/guji-ocr）
- 采集类入口调用 require_wd()：外置盘未挂载直接报错退出，绝不静默回退本地
  （历史教训：分散的 fallback 目录不存在也不报错，会造成数据静默分裂）
- var/ 为仓库本地数据（gitignore 整目录），与挂载无关
- REPO_ROOT 由本文件位置推导（tools/ 的上一级），仓库整体搬迁无需改代码

用法（各入口脚本顶部）：
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import paths  # noqa: E402
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WD_ROOT = Path(os.environ.get("GUJI_WD_ROOT", "/Volumes/WD-2T/guji-ocr"))

# ---- 外置盘：自采原始数据（raw/，只增不改，按站点分组） ----
RAW_KANGXI_PAGES = WD_ROOT / "raw" / "kangxizidian" / "pages"      # 整页扫描 NNNN.jpg
RAW_KANGXI_ENTRIES = WD_ROOT / "raw" / "kangxizidian" / "entries"  # 字头详情 JSON（按码位命名）
RAW_KANGXI_SVG = WD_ROOT / "raw" / "kangxizidian" / "heads-svg"    # 字头 SVG 缓存（分桶）

# ---- 外置盘：第三方数据集（datasets/）与状态库快照（backup/） ----
DATASETS_DIR = WD_ROOT / "datasets"
BACKUP_DIR = WD_ROOT / "backup"

# ---- 仓库本地 var/（可再生缓存与工作状态；sqlite 主库只留本地，不上 exFAT） ----
VAR_DIR = REPO_ROOT / "var"
CRAWL_DB = VAR_DIR / "crawl" / "kangxi-crawl.sqlite3"
CRAWL_EVENTS = VAR_DIR / "crawl" / "kangxi-crawl-events.jsonl"
SVG_BACKFILL_EVENTS = VAR_DIR / "crawl" / "kangxi-svg-backfill-events.jsonl"
DEMO_CACHE_DIR = VAR_DIR / "crawl" / "kangxi-demo-cache"
OCR_CACHE_DIR = VAR_DIR / "ocr-cache"          # 共享 OCR markdown 缓存（NNNN.json）
UNENCODED_DIR = VAR_DIR / "unencoded"          # 未编码字头分析产物（svg/png/报告/补丁日志）
LOGS_DIR = VAR_DIR / "logs"


def wd_mounted() -> bool:
    """外置盘根目录是否可用。"""
    return WD_ROOT.is_dir()


def require_wd(what: str = "采集") -> None:
    """采集类入口的防呆：未挂载直接退出，不回退本地。

    只读/缓存类脚本不要调用本函数（本地 var/ 与挂载无关）。
    """
    if not wd_mounted():
        print(
            f"✗ {what} 需要外置盘 {WD_ROOT}（未挂载）。挂载后重试，"
            f"或设 GUJI_WD_ROOT、或用 --xxx-dir 显式指定路径。规范见 docs/data-storage.md",
            file=sys.stderr,
        )
        raise SystemExit(2)
