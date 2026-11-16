# 增量构建古籍版式与文字 OCR 数据集

构建入口：`tools/dataset/build_ocr_dataset.py`。默认读取 `kangxi-gold/manifest.json`，
仅纳入 `first`、`final` 页面，以当前 `.gj` 为唯一转写源，在内存中调用生产 `gj2ir`、
`layout3`、`planLayoutBand`、`projectBooks` 与 `irToText`，不要求先手动同步源库 JSON/TXT，
也不覆盖源库的三件套。生成的 IR/TXT 随构建保存。

首批六页及全量 45 页的实际结果见 [构建验收](../research/2026-11-16-OCR数据集构建验收.md)。
算法、原图候选定位公式及实测算例见 [构建技术报告](../research/2026-11-16-古籍OCR数据集构建技术报告.md)。

## 使用

要求 Node ≥22.18（原生 TypeScript stripping）和 Python ≥3.9。Python 依赖：

```sh
python3 -m pip install -r tools/dataset/requirements-ocr.txt

# 首批六页（原图目录读取 manifest.images_dir，需挂载 WD-2T）
python3 tools/dataset/build_ocr_dataset.py --pages 312,333,318,328,342,349

# 全部初校／精校页；以后新增初校页或修改旧页，仍执行同一条命令
python3 tools/dataset/build_ocr_dataset.py

# 可选：指定输出、扫描图、manifest 或定位修订目录
python3 tools/dataset/build_ocr_dataset.py --output /absolute/output/path

# 浏览核对页面（无需 OCR 服务、Vite 或网络）
python3 -m http.server 8940 --bind 127.0.0.1 --directory var/datasets/kangxi-ocr
# 浏览器打开 http://127.0.0.1:8940/review.html

# 导入核对页下载的坐标修订，并重建受影响页面
python3 tools/dataset/build_ocr_dataset.py --import-review /absolute/path/guji-ocr-review.json
```

无需每次使用 `--force`。初校状态在源 manifest 更新后，下次执行自动纳入。
本工具是按需运行的增量构建，不是后台监控任务。

## 输出

默认输出属于可再生缓存，放在 `var/datasets/kangxi-ocr/`，不进 git。
原图仍由 `manifest.images_dir` 定位，构建包另存原图副本，可独立浏览。

```text
manifest.json                 当前有效页面、输入/实现/输出哈希、错误与统计
last-build.json               本次 built / skipped / deferred / errors
pages.jsonl                   整页图→文字，共用 source_page_id / split_group
recognition.jsonl             大列和文字片段裁剪→文字
pua.json                      私用区码点、字体文件、图中位置、已有登记
review.html                   可离线使用的核对页（可选本机 HTTP 服务）
objects/0312/<fingerprint>/
  scan.jpg                    原图副本
  synthetic.png               干净渲染图
  scan.json / synthetic.json  各自坐标系的结构化标注
  scan-overlay.jpg            原图文字片段叠框
  synthetic-overlay.jpg       合成图文字片段叠框
  source.gj / ir.json / text.txt
  provenance.json             本页完整输入哈希与定位修订
  crops.json                  本页裁剪清单
  crops/{scan,synthetic}/     大列、局部小字 run、大字／合字格 PNG
```

图片标签 schema 为 `guji-ocr/1`：

- `bands`、`regions`、`glyphs`、`gaps`、`decorations` 分开；空格不作为文字框。
- `regions` 的 `kind` 为 `large` 或 `text_run`；`size_class` 不自动代表正文／夹注语义。
- `text_range` 为清洗后非空白文本中的 Unicode 码点半开区间；`source.raw_range`
  为 IR line 原文码点区间。合字一个格对应多个码点。源码 UTF-16 映射仍保留于 IR。
- `bbox` 为图像像素 xyxy 半开框，明确 `bbox_type`；字格占位框不等于笔画紧框。
- 合成 `glyphs.ink_bbox` 为抗锯齿缩小前独立字形掩码范围，不含书名框／圈线；
  `decorations` 保留书名片段 open 状态和圈号目标。
- `reading_order` 和 `glyph_reading_order` 来自 IR／布局计划，绝不以 DOM 顺序排序。
- `overlays` 保留 IR 语义引用；逐页开口状态保留，未虚构全书跨页书名统一 ID。
- 原图 `ignore_regions` 覆盖估计正文框之外的区域，随候选定位一起复核。

`pages.jsonl` 可用于整页转写；`recognition.jsonl` 含两种域的裁剪及 `geometry_status`。
训练识别器时先筛选域／框状态。定位训练可直接使用合成标签；原图的自动框不可作为终校金标。

## 渲染与原图定位的边界

合成图片采用 `guji-grid-pillow/1` 栅格后端，复用生产网格规则和仓库字体，
用两倍分辨率抗锯齿。它不是浏览器 CSS 截图，与浏览器预览不保证逐像素相同。
不读取系统回退字体；缺字、空轮廓、排版警告、文本读序不一致、字格越界会使该页失败。
每页带实现、字体、依赖版本与渲染样式指纹。

原图定位使用扫描版框、列间墨迹谷值及有界纵向墨迹拟合，并以 IR 提供局部大小字结构；
不依赖变化中的 OCR 缓存或 OCR 服务。当前定位器只支持本书的 8 大列／16 小格／24 行布局。
它会排除鱼尾版心及页脚，仍可能在倾斜、破损、错位上有局部偏差。

原图总体 `geometry_status=proposed`；单独修订的 region 可为 `reviewed`，
但其子字格不会随之被宣布为已复核。`band_geometry_status=reviewed` 也仅表示大列。
`ink_fraction`、`quality_flags` 是排查线索，不是概率或准确率。所有原图框应在核对页叠图复核。

核对页支持页面、输入域、标注层及缩放切换；点击框显示文本／读序。
可以编辑原图的大列框或文字片段框，下载 JSON 后导入；大列修订会在重建后作用于子框。
修订保存到 `kangxi-gold/scan-reviews/NNNN.json`，属于需版本管理的人工标注。
更改 `.gj` 后 ID 可能移动，旧修订会报 stale；重新复核并显式归档旧修订后再导入，不应只替换哈希绕过检查。

## 增量与失败恢复

每页指纹包含 `.gj`、原图、状态、尺寸、来源、该页修订、解析／排版／导出代码、
字体及运行依赖版本。新增页只构建新增页；修订只影响相关页；公共实现或字体变化重建相关构建。
跳过前检查所有产物哈希，缺文件或损坏会重建。

每页先在临时目录生成并验收，再移入版本目录；旧版本保留。损坏的同指纹目录改名为
`.damaged-*` 留存。输出目录使用文件锁，避免两个构建同时写入。索引文件逐文件原子替换，
退出码非零时应查 `last-build.json`，不要直接视为完整成功。

降为 `draft`、从源清单移除、源发生变化但未选中重建、或本轮失败的页，会从当前索引移除，
旧对象不删除。`--pages` 是本轮允许构建的集合，其他指纹完整的页面仍保留在索引。
解析与渲染失败按页隔离，有效页面继续构建。源图哈希不符时明确失败，不会自动重下载或替换原图。

当前所有样本都使用 `kangxi-wuyingdian-development` 分组。正式训练／验证划分应先按书、
版本或连续页组确定，再展开原图、合成图、裁剪与增强；不要随机拆同源图像。

## 验证

```sh
python3 -m unittest discover -s tools/tests -v
python3 tools/dataset/build_ocr_dataset.py
python3 tools/dataset/build_ocr_dataset.py   # 应 built=[]，全部 skipped
python3 tools/dataset/verify_ocr_dataset.py  # 独立核对当前输出的标签、图像和裁剪
```

语料级验收包括：图片尺寸、标签界限、读序一致、空白排除、合字码点计数、PUA 字形以及产物哈希。
这不等于重新逐字终校，也不构成 OCR 模型性能评测。
