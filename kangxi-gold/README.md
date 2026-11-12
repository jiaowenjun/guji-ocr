# kangxi-gold：康熙字典自建精标金标

康熙字典**武英殿版·子集上·一部** 17 页（@312–@328）的整页**文本级金标** v1，
对应 [docs/research/README.md §11 评测协议](../docs/research/README.md#evaluation)
阶段 1 的第一个自有开发样本。

| 项 | 值 |
| --- | --- |
| 规模 | 17 页，正文 5,933 字（Unicode 码点，含扩展 B 区） |
| 图片 | 整页扫描 JPEG（1130px 宽），共 9.04 MB，存于 WD-2T（见下） |
| 标注来源 | [guji-preview/src/samples/kangxi-yibu.gj](../guji-preview/src/samples/kangxi-yibu.gj) 人工精标（源自 vscode-guji-preview 扩展 example） |
| 金标版本 | v1（2026-11-12） |

## 目录结构

```
kangxi-gold/
  manifest.json            页清单：来源 URL、图片 sha256/尺寸/路径、标注文件、版本证据
  annotations/NNNN.gj      单页 .gj 原文（按 @页码 拆分，逐行原样保留）
  annotations/NNNN.json    结构化金标（guji-preview 解析器的单页输出，PageModel）
  annotations/NNNN.txt     阅读序纯文本（CER 参考文本）
  scripts/download_pages.py   下载扫描图（限速、校验、断点续传、维护 manifest）
  scripts/build_annotations.ts 拆页 + 解析 + 零漂移校验 + 产出三件套
  scripts/verify_dataset.py    数据集一致性校验
  scripts/eval_cer.py          严格 CER 评测（对接 paddleocr-baseline 输出）
图片不在 git 内：/Volumes/WD-2T/guji-ocr/datasets/kangxizidian-wuyingdian/NNNN.jpg
```

## 来源与页码对齐验证

- 图片来源：[kangxizidian.com](https://www.kangxizidian.com/v2/)（康熙字典網上版），
  站点默认版本即**武英殿版**，整页图直链 `https://p.kangxizidian.com/kangxi2/NNNN.jpg`。
- 页码体系与 .gj 样例一致：站点部首检索「一」→ `index.php?page=312`，即 .gj 的 @312。
- 目视核对（2026-11-12，下载证据见
  [evidence/2026-11-12-kangxi-gold-images.json](../docs/research/evidence/2026-11-12-kangxi-gold-images.json)）：
  - **0312**：版心「康熙字典 子集上」，页首标题「康熙字典/子集上/一部」，唯一字头「一」+古文「弌」，
    注文开头「【唐韻】【韻會】於悉切…」与 .gj 逐字吻合；
  - **0315**：始于「丁」条续文，「丂」字头注文（苦浩切音考、玉篇古文巧字註詳工部二畫）逐句吻合；
  - **0328**：增补字头页，「增/增/七/十/十五」带圈标注序列与 .gj 吻合。
- 每页扫描图页脚有站点水印（`kangxizidian.com` + 页码），非原书内容。

## 扩页与页标签

- 经 guji-preview-grid「添加新页」录入：`scripts/kangxi_page_tool.py` 以 sqlite
  （`datasets/kangxi-crawl.sqlite3`，已有数据零联网）+ 站点增量爬取生成 .gj 草稿，
  manifest 记 `status`；草稿页校对完成后跑 `build_annotations.ts --allow-drift`
  同步 json/txt（样例外附加页自动处理），`verify_dataset.py` 默认按 manifest 页清单校验
- 页标签：`draft` 草稿（爬取生成）→ `first` 初校（人工校对过）→ `final` 精校
  （复核确认）；v1 的 17 页（312–328）定为初校
- `NNNN.json` 为 **Guji IR v1**（语义结构：页→大行→段流；书名以 parts 表达跨行；
  text 段保留标点，清洗口径在 `meta.profile`；设计见
  [docs/design/guji-ir.md](../docs/design/guji-ir.md)），manifest 记
  `annotations_schema: guji-ir/1`；`eval_cer.py --from-ir` 可直接读 IR 作参考文本

## 标注规范

- 语法与语义以 [guji-preview 的 .gj 语法](../guji-preview/README.md) 为准；
  构建时与 `guji-preview/test/fixtures/kangxi-yibu.expected.json`
  （原扩展解析器黄金期望）做**零漂移对照**，单页解析 = 整篇解析 = fixture。
- **识别范围**：字头（大字）、正文、双行夹注（小字）、书名框、带圈标注入金标；
  版心、边框、鱼尾、印章、页脚水印**不在**金标内。
- **清洗约定**（解析器预处理，金标侧已发生）：剔除 CJK 标点 `。，·":：、《》`，
  全角空格转空格标记，`//` 注释行丢弃。
- **忠实转写**：异体字、扩展 B 区字（𠀤 等）原样保留，不做繁简/异体归并。
- **阅读序**：以 .gj 转写序为准（夹注按转写者折行顺序展开）；
  TXT 每个大行（band）一行，标题行保留（0312 页首的三级标题为原书实有内容）。
- **无坐标**：v1 为纯文本金标，支持整页 CER 条件；行/字定位（IoU 指标）留待后续
  用 OCR 对齐半自动补充。

## 用法

```bash
# 1. 下载/补齐图片（WD-2T 需挂载；可用 --images-dir 换路径）
python3 scripts/download_pages.py

# 2. 重建标注
#    严格模式（默认）：以 guji-preview 样例为唯一源重新生成三件套，
#    与 fixture 零漂移校验；检测到人工修订页会拒绝执行（防覆盖）
npx -y tsx scripts/build_annotations.ts
#    --allow-drift：人工修订模式——annotations/NNNN.gj（如经 guji-preview-grid
#    数据集对照页保存的校对）视为源，不被样例覆盖，json/txt 从修订版重新生成，
#    修订页列入 drift 清单供 git diff 审查
npx -y tsx scripts/build_annotations.ts --allow-drift

# 3. 校验数据集一致性
python3 -I scripts/verify_dataset.py

# 4. 评测：paddleocr-baseline 批量输出目录（每图 <stem>.md）→ 严格 CER
python3 -I scripts/eval_cer.py --ocr-dir <批量输出目录> [--json 结果.json]
python3 -I scripts/eval_cer.py --self-test   # S/D/I 对齐自测
```

评测口径：两侧施加同一清洗函数（去空白 + 显式标点集，含书名框括号与圈号），
不做任何 Unicode 归一化/繁简转换；CER = (S+D+I)/N，报微平均、页均与 S/D/I 分项；
缺失/空输出按全删计，不剔除失败页。注意页脚水印字符会被 OCR 读出并计入插入错误，
属真实差异，不清洗。gold vs gold 全链路冒烟：微平均 CER = 0.0000（2026-11-12）。

## 已知边界

- 17 页 < 协议建议的 20–30 页开发样本规模；扩页需新的人工转写
  （站点无纯文本，页面文字由逐字 SVG 渲染）。
- 图片版权归 kangxizidian.com / 原书相关方；本数据集仅供内部研究评测。
- 同书相邻页不可跨开发/测试分组划分（协议 §11.1）。
