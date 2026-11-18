# guji-large.ttf 首例 K0000 补录落地报告（U+2BD6E 𫵮）

> 2026-11-18 勘误：本文历史记录中的 U+2BD6E「Ext-C」应为 **Ext-E（扩展 E，U+2B820–U+2CEAF）**。码位、字体操作和核验结果不变；依据与完整时间线见[字体补录 Changelog](../font-changelog.md)。

补录执行于 2026-11-13，本报告撰写并全量复核于 2026-11-14，同时作为[字体操作留痕登记簿](../font-operations.md)制度化的首份详报。操作手册（怎么补）见 [字体补录流程](2026-11-13-kangxi-字体补录流程.md)，身份判定（为什么是 U+2BD6E）见 [未编码字头字体核验流程](2026-11-13-kangxi-未编码字头字体核验流程.md)；本文只记录**实际做了什么、结果如何、如何验证与回滚**。

## 1. 摘要

site 334 页第 4 字头（K0000 占位）经 kKangXi 槽位仲裁认定为 **U+2BD6E 𫵮**（Ext-C，classic 79 页槽 9，丰与丱之间）——首个也是迄今唯一一个康熙字典體（KX_47043_14）不覆盖的字头（Ext-C 零覆盖）。以站方字头缩略图 SVG 为字形源、同页邻字「丰 U+4E30」为校准锚，向仓库字体 `guji-preview-grid/public/fonts/guji-large.ttf` 与系统字体 `~/Library/Fonts/KX_47043_14.ttf` 各注入字形 `u2BD6E`（2 轮廓，bbox (88,−135,944,735)，advance 1024，校准 scale 0.8739），验证闸 chamfer 0.029（阈值 0.15，余量 5 倍），原子替换落盘，双字体 cmap 同步 49,407→49,408。提交 0ca95d6，缓存戳 `?v=001015-2bd6e`。2026-11-14 复核：哈希、cmap、渲染、备份全部完好；修复了一处补录日志路径漂移（§7）。

## 2. 时间线

| 时间 | 事件 |
| --- | --- |
| 11-12 16:37 | 80cea9a：四字体文件入库仓库（guji-large 与系统字体字节级同源，sha `dfc5876c…`） |
| 11-13 白天 | 核验流程完成，U+2BD6E 身份定案；文档提交 fc2dfae 18:28 |
| 11-13 晚 | 方案 A PoC：/tmp 副本上跑通「SVG→轮廓→注入→chamfer 0.029」，/tmp 可视化预览页（@font-face 三联对比 + 字典语境行「丮丯丰𫵮丱」）目视确认风格统一、基线对齐 |
| 11-13 19:40 | 系统字体备份至 `~/.kx-font-backup/KX_47043_14-v001014-orig.ttf`（目录在 Fonts 外，防 fontd 注册） |
| 11-13 19:41:39 | 正式脚本双字体补录，jsonl 流水落盘 |
| 11-13 21:16:40 | 提交 0ca95d6：字体 Bin 46,698,456→46,623,752 B + index.css 缓存戳 + `scripts/kangxi_font_patch.py`（206 行） |
| 11-14 16:39 | bcaed54 仓库重构：脚本迁至 `tools/dataset/kangxi_font_patch.py`，产物目录 `datasets/kangxi-unencoded/` → `var/unencoded/kangxi-unencoded/` |
| 11-14 | 本报告撰写 + 全量复核 + 路径漂移修复 + 登记簿制度建立 |

## 3. 实际执行记录

命令（按重构后路径）：

```bash
python3 tools/dataset/kangxi_font_patch.py \
  --font guji-preview-grid/public/fonts/guji-large.ttf \
  --font ~/Library/Fonts/KX_47043_14.ttf \
  --svg        var/unencoded/kangxi-unencoded/svg/0334-04-K0000.svg  --cp 2BD6E \
  --anchor-svg var/unencoded/kangxi-unencoded/svg/0334-03-00054-4E30.svg --anchor-cp 4E30
```

机器流水 `var/unencoded/kangxi-unencoded/font-patches.jsonl` 原文（唯一一条，2026-11-13T19:41:39；`svg` 字段中的路径为重构前的 `datasets/…`，文件现都在 `var/unencoded/kangxi-unencoded/`）：

```json
{"at": "2026-11-13T19:41:39",
 "svg": "…/datasets/kangxi-unencoded/svg/0334-04-K0000.svg",
 "results": [
  {"font": "guji-preview-grid/public/fonts/guji-large.ttf", "cp": "U+2BD6E", "glyph": "u2BD6E",
   "scale": 0.8739, "bbox": [88, -135, 944, 735], "advance": 1024, "chamfer": 0.029,
   "bytes_before": 46698456, "bytes_after": 46623752},
  {"font": "/Users/jwj/Library/Fonts/KX_47043_14.ttf", "cp": "U+2BD6E", "glyph": "u2BD6E",
   "scale": 0.8739, "bbox": [88, -135, 944, 735], "advance": 1024, "chamfer": 0.029,
   "bytes_before": 46698456, "bytes_after": 46623752}]}
```

字形源与锚 SVG 哈希（2026-11-14 实测）：源 `0334-04-K0000.svg` `40aca218281b9efe68b7046acac6448684457cf34cf5a756d65fb857d00f13fd`；锚 `0334-03-00054-4E30.svg` `79391933238c65e3e99cf0f0eb07996875eb5361a16b8ee5e27ff7f5ee743a45`。

## 4. 结果与验证

| 项 | 补录前 | 补录后 | 验证方式 |
| --- | --- | --- | --- |
| guji-large.ttf sha256 | `dfc5876c1a580922…5256da87f`（=备份=80cea9a blob） | `99be6a77b93afa74…6760a17dabf` | 11-14 实测三方比对 |
| 系统字体 sha256 | 同上 | `7d916ab6e4bcc935…e2dbb9c4fa` | 同上 |
| cmap（双字体） | 49,407（BMP 24,858 + Ext-B 24,548 + Ext-G 1） | **49,408**（+Ext-C 1：U+2BD6E；平面分布 {0:24858, 2:24549, 3:1}） | fontTools getBestCmap 双字体实测 |
| 字形保真 | — | chamfer 0.029（闸 0.15；基线「丰 扫描vs原生」0.035，即与原生字形同量级） | 脚本内置闸 + /tmp 四联预览目视 |
| 体积 | 46,698,456 B | 46,623,752 B（loca 重排后略小 75KB） | jsonl 前后字节数 |
| 浏览器生效 | — | index.css GujiLarge `?v=001015-2bd6e`（url() 保持 src 首位） | 0ca95d6 diff |

已知无害差异：仓库版与系统版补录后 sha 不同（fontTools 写出的 3 字节头部校验和区差异），表数据一致、渲染一致，以验证闸与渲染为准（手册坑清单已载）。

## 5. 影响面与未做部分

- **生效范围**：`.large` 大字视图、字头条/字头详情弹窗、编辑器 `.cm-guji-large-char`（GujiLarge 第一优先的栈全部受益）；small 小字矩阵**不受益**——其栈是 GujiPlane0→2→F，U+2BD6E 落 plane2（中华书局宋体现代风格，本就有该字），未按康熙风格补录 plane2。维持现状的理由：小字正文以可读性优先，逐字风格统一需求出现时再按同流程跑 plane2。
- **部署**：guji-large.ttf 已在仓库（public/fonts/），任何部署自带补录结果；缓存戳保证浏览器不持旧版。
- **系统字体消费者**：CoreText 按进程缓存，改后需重启应用才见新字形。

## 6. 回滚手册

- **仓库字体**：`git checkout 80cea9a -- guji-preview-grid/public/fonts/guji-large.ttf`（或任意补录前 blob），同时把 index.css 缓存戳再递增一次强制刷新。
- **系统字体**：`cp -p ~/.kx-font-backup/KX_47043_14-v001014-orig.ttf ~/Library/Fonts/KX_47043_14.ttf`，重启相关应用。
- 两路回滚后 cmap 回到 49,407，字头 0334-04 的显示退回 plane2/系统兜底（不缺字，只是风格不统一）。

## 7. 本次（11-14）留痕治理：补录日志路径漂移修复

bcaed54 重构把产物目录 `datasets/kangxi-unencoded/` 改到 `var/unencoded/kangxi-unencoded/`，但 `kangxi_font_patch.py` 的 `PATCH_LOG` 常量停在中途形态 `var/unencoded/font-patches.jsonl`——**下次补录会把流水写进一个新文件，与历史日志分裂**。本次修复：常量与 docstring 示例路径统一改为 `var/unencoded/kangxi-unencoded/font-patches.jsonl`；[字体补录流程](2026-11-13-kangxi-字体补录流程.md)与[核验流程](2026-11-13-kangxi-未编码字头字体核验流程.md)两文中的 5 处 `datasets/kangxi-unencoded` 旧路径同步更正。字体文件字节未动。

这正是登记簿制度的动机之一：路径与哈希若不集中留痕，重构一次就能让审计链断掉。

## 8. 制度化

自本报告起，所有字体操作（补录/改字形/换文件/缓存戳/系统字体同步）必须双轨留痕：脚本 jsonl 自动流水 + [docs/font-operations.md](../font-operations.md) 人工登记（含前后哈希、验证数值、提交、回滚点）。登记簿已回填本次 #1 操作与 2026-11-14 六份字体文件全量哈希基线。
