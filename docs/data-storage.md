# 数据文件存放规范

> 制定日期：2026-11-14（目录重构落地日）。本规范是全仓库数据落盘的**唯一依据**；
> 路径的代码事实源是 [`tools/paths.py`](../tools/paths.py)，两者不一致时以先更新者为准同步另一处。

## 一、分层判定表

新文件落盘前先回答「它是什么」，按类归位：

| 类别 | 定义 | 位置 | 例外与理由 |
| --- | --- | --- | --- |
| **代码 / 文档 / 金标** | 人写的、需要版本管理的文本 | git 仓库（`src/`、`tools/`、`docs/`、`kangxi-gold/annotations/` 等） | — |
| **刻本字体** | `guji-preview-grid/public/fonts/*.ttf`（128M） | git 仓库内 | Safari `local()` 伪命中须 url() 直载；克隆即用、部署自包含。是 git 内唯一的大文件例外 |
| **可再生缓存 / 工作状态** | 丢了能重算、或随进度自会重建 | 仓库本地 `var/`（整目录 gitignore） | OCR 缓存丢了重跑 prefetch；demo 缓存/日志随建随有 |
| **爬取状态库** | `var/crawl/kangxi-crawl.sqlite3`（93M+，随全书爬取增长） | **只留仓库本地**，定期快照到 WD `backup/` | exFAT 无 POSIX 锁、断写易损坏，SQLite 高频写**禁止**直接落外置盘 |
| **自采原始数据** | 爬虫抓来的、丢了要重爬（礼貌限速下代价极高） | WD-2T `raw/<站点>/<类别>/`，只增不改 | — |
| **第三方数据集** | 下载的调研数据集 | WD-2T `datasets/<名称>/`（原始包 + 解压目录并存） | 原始 zip 保留作溯源校验，不删 |
| **状态库快照** | sqlite/events 的备份副本 | WD-2T `backup/` | 见 §四 |
| **一次性工作区** | crack-work 等 | WD-2T 顶层，不动 | 历史遗留 |

**采集类不回退原则**：爬虫/落盘类脚本（`tools/crawl/*`）外置盘未挂载时**直接报错退出**
（`paths.require_wd()`），绝不静默写到本地——历史教训：分散的 fallback 目录不存在也不报错，
数据会静默分裂成两处。只读/缓存类脚本不受此约束。

## 二、当前位置清单

### 仓库（git + var/）

```
guji-ocr/
├── docs/                    # 文档（本规范在此）
├── guji-preview-grid/       # 前端应用；public/fonts 128M 随 git
├── paddleocr-baseline/      # OCR 服务；data/ocr 为服务私有存储（gitignore）
├── kangxi-gold/             # 金标数据集；annotations/ 84 文件随 git
├── tools/                   # 脚本，按链路分域
│   ├── paths.py             # ★ 全部路径常量的代码事实源
│   ├── crawl/               # 爬取：fetch_*、kangxi_store、kangxi_crawl_*、svg_cache、verify
│   ├── dataset/             # 数据集：kangxi_page_tool、kangxi_font_patch、make_manifest
│   ├── eval/                # 评测与 OCR 辅助：eval_*、column_seg*、prefetch_ocr
│   └── download/            # 通用下载：hf_snapshot、parallel_fetch
└── var/                     # gitignore 整目录；结构见下
    ├── crawl/               #   kangxi-crawl.sqlite3（状态库）+ *-events.jsonl + kangxi-demo-cache/
    ├── ocr-cache/           #   共享 OCR markdown 缓存 NNNN.json（prefetch_ocr 产，5 处消费）
    ├── unencoded/           #   未编码字头分析产物：svg/ png/ report + font-patches.jsonl
    └── logs/                #   crawl.log、demo.log
```

### 外置盘 /Volumes/WD-2T/guji-ocr/（exFAT，1.8T）

```
├── datasets/                # 第三方数据集（46G）
│   ├── ancientdoc/          #   5.0G AncientDoc（imgs 16 类 + label.csv；内含 HF 缓存 452M）
│   ├── ancientdoc-ocr-mini/ #   17M AncientDoc_OCR 代码包
│   ├── casia-ahcdb/         #   18G CASIA-AHCB（style1/2 × basic/enhanced；6 个原始 zip 并存）
│   ├── chronicles-ocr/      #   1.8G Chronicles-OCR（按字体 7 类 + eval）
│   ├── hisdoc1b/            #   8.0G data.zip——HisDoc1B 加密包（申请被拒，拒绝破解）
│   ├── gxdq/                #   国学大全 PDF（10002/ 卷册 + 卷一）
│   ├── mthv2/               #   11G MTH1000/1200 + TKH（含 TKHMTH2200.zip 4.6G）
│   └── MANIFEST.json        #   下载清单（make_manifest.py 生成）
├── raw/                     # ★ 自采原始数据（只增不改，按站点分组）
│   └── kangxizidian/
│       ├── pages/           #   整页扫描 NNNN.jpg（kangxi-gold 的 images_dir 指此处）
│       ├── entries/         #   字头详情 JSON（按码位命名，20000.json…）
│       └── heads-svg/       #   字头 SVG 缓存（0000s–7000s 分桶）
├── backup/                  # ★ 状态库快照（§四）
└── crack-work/              # zip 密码破解历史工作区（1.0G，保留不动）
```

kangxi-gold 扫描图的路径契约：`kangxi-gold/manifest.json` 的 `images_dir` 字段是
**唯一事实源**（下载、校验、前端 link-dataset.sh 都读它）；当前值
`/Volumes/WD-2T/guji-ocr/raw/kangxizidian/pages`。

## 三、代码里怎么取路径

- 一律 `import paths`（`tools/paths.py`），不要在脚本里写 `/Volumes/...` 字面量；
  `GUJI_WD_ROOT` 环境变量可整体重定向外置盘根（换盘/换机器零改码）。
- 各脚本保留 `--xxx-dir` CLI 覆盖；默认值来自 paths。
- 跨子目录 import 用既有的 sys.path bootstrap 模式（入口脚本把 `tools/`、
  `tools/crawl/`、`tools/dataset/` 按需插入 sys.path）。
- 例外：`kangxi-gold/scripts/` 保持自包含（数据集工具不依赖 tools/），
  其 `download_pages.py` 的默认 images-dir 字面量须与 paths 保持同步。

## 四、备份（var → WD backup/）

爬取状态库是全书爬取进度的唯一记录，损坏 = 重爬。定期（建议每周或每 ~500 页）快照：

```sh
# SQLite 必须用在线备份法（cp 活库有 WAL 撕裂风险）
sqlite3 var/crawl/kangxi-crawl.sqlite3 ".backup '/Volumes/WD-2T/guji-ocr/backup/kangxi-crawl.sqlite3'"
# 事件日志增量同步（排除 exFAT 的 AppleDouble 垃圾）
rsync -a --exclude '._*' --exclude '.DS_Store' var/crawl/*-events.jsonl /Volumes/WD-2T/guji-ocr/backup/
```

## 五、exFAT 注意事项

- **无符号链接**：符号链接只能建在仓库侧指向 WD（`link-dataset.sh` 机制），不能建在盘上。
- **AppleDouble `._*`**：macOS 写 exFAT 自动产生元数据垃圾，清理用 `dot_clean -m <目录>`；
  rsync 到盘上永远带 `--exclude '._*'`。
- **无 POSIX 锁**：SQLite 禁止直接建在盘上（WAL/锁失效，断写即损坏）——只放快照。
- 大批量小文件（entries JSON、svg）在 exFAT 上目录项膨胀明显，分桶目录已是既有做法，沿用。

## 六、hf_snapshot 下载环境（已删的 scripts/.venv-dl 重建法）

`tools/download/hf_snapshot.py` 需要 huggingface_hub；原 `scripts/.venv-dl`（35M）已删，
需要时重建：

```sh
python3 -m venv tools/.venv-dl && tools/.venv-dl/bin/pip install huggingface_hub
tools/.venv-dl/bin/python tools/download/hf_snapshot.py <repo> <target_dir>
```
