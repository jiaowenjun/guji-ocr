# 参考文献与来源

本页是[综合调研报告](README.md)的来源索引，覆盖已调研的 27 篇论文、8 篇古籍酷文章和 7 篇微信文章。核查截至 **2026-11-11**；作者／厂商成绩未在本仓库复现。资源获取、许可和文件核查以 [resources.json](resources.json) 及[证据说明](evidence/README.md)为准。

## 建议阅读顺序

先用 SCUT-CAB、M5HisDoc、EvaHan 理解标注和评价，再读 Reading between the Lines、RGD 与 PageNet 理解顺序和定位。选定工程路线后读 PaddleOCR 或文档 VLM 报告；AncientDoc、Chronicles 与已有文件核查应结合阅读，避免直接把发布文本当作无误金标。

论文的 A／B／C 优先级来自资源索引，表示与本项目的关系，不代表论文质量排名。下表单列核查深度；“摘要／仓库已读”不表示全文已读或实验已复现。

<a id="papers"></a>
## 一、论文书目

### 古籍数据、版式与评价

| 论文与出版信息 | 优先级／阅读目的 | 已完成核查 |
| --- | --- | --- |
| [SCUT-CAB: A New Benchmark Dataset of Ancient Chinese Books with Complex Layouts for Document Layout Analysis](https://github.com/HCIILAB/SCUT-CAB_Dataset_Release)，ICFHR，2022；索引 ID：`cheng2022` | A；物理／逻辑类别与古籍语义版式定义 | 作者项目介绍及引用条目；未阅读全文 |
| [M5HisDoc: A Large-scale Multi-style Chinese Historical Document Analysis Benchmark](https://proceedings.neurips.cc/paper_files/paper/2023/hash/f7b424d242cc6bb7708cff241367334d-Abstract-Datasets_and_Benchmarks.html)，NeurIPS Datasets and Benchmarks，2023；索引 ID：`shi2023` | A；多样式字／行标注、增强及跨库原页复用 | 作者数据仓库及其书目信息；论文链接由HisDoc1B作者仓库提供 |
| [Joint Layout Analysis, Character Detection and Recognition for Historical Document Digitization](https://doi.org/10.1109/ICFHR2020.2020.00017)，ICFHR，2020；索引 ID：`ma2020` | A；联合版式、字检测、识别；MTHv2 出处 | 作者数据仓库及Crossref书目 |
| [A large-scale dataset for Chinese historical document recognition and analysis](https://doi.org/10.1038/s41597-025-04495-x)，Scientific Data，2025；索引 ID：`shi2025` | B；HisDoc1B 半自动构造、长尾字与规模化训练 | PMC公开全文、作者仓库、数据元数据已读 |
| [Overview of EvaHan2026: The First International Evaluation of Ancient Chinese OCR and Layout Analysis](https://aclanthology.org/2026.lt4hala-1.23/)，LT4HALA @ LREC，2026；索引 ID：`wang2026` | A；分任务、样本粒度、异体字规则与比赛协议 | ACL书目摘要、论文全文相关页及作者仓库已核对 |
| [Benchmarking Vision-Language Models on Chinese Ancient Documents: From OCR to Knowledge Reasoning](https://aclanthology.org/2026.findings-acl.1438/)，Findings of ACL，2026；索引 ID：`yu2026` | A；整页 VLM 转写与理解；标签构建和发布核查 | ACL书目摘要、论文全文相关页、作者仓库、HF卡已核对；预印本2025 |
| [CASIA-AHCDB: A Large-Scale Chinese Ancient Handwritten Characters Database](https://doi.org/10.1109/ICDAR.2019.00132)，ICDAR，2019；索引 ID：`xu2019` | C；手写单字与风格、类别覆盖 | 机构数据页及Crossref书目 |
| [ICDAR 2019 Historical Document Reading Challenge on Large Structured Chinese Family Records](https://arxiv.org/abs/1903.03341)，ICDAR，2019；索引 ID：`saini2019` | C；家谱挑战及来源集合与标注子集的区别 | 作者arXiv摘要及书目 |
| [Chronicles-OCR: A Cross-Temporal Perception Benchmark for the Evolutionary Trajectory of Chinese Characters](https://arxiv.org/abs/2605.11960)，arXiv，2026；索引 ID：`li2026_chronicles` | B；跨书体任务、框匹配与文本评分公式 | 论文v2方法/指标、官方仓库与实际标签已核对 |

### 检测、识别与阅读顺序方法

| 论文与出版信息 | 优先级／阅读目的 | 已完成核查 |
| --- | --- | --- |
| [Dense and Tight Detection of Chinese Characters in Historical Documents: Datasets and a Recognition Guided Detector](https://doi.org/10.1109/ACCESS.2018.2840218)，IEEE Access，2018；索引 ID：`yang2018` | B；识别引导紧致框；严格 IoU 和单行输入前提 | IEEE论文全文、Crossref书目与作者仓库表1/4/5已核对；未复现实验 |
| [HRCenterNet: An Anchorless Approach to Chinese Character Segmentation in Historical Documents](https://arxiv.org/abs/2012.05739)，IEEE Big Data，2020；索引 ID：`tang2020` | B；密集单字 anchor-free 检测，区别于识别 | 作者代码及arXiv摘要 |
| [PageNet: Towards End-to-End Weakly Supervised Page-Level Handwritten Chinese Text Recognition](https://arxiv.org/abs/2207.14807)，IJCV，2022；索引 ID：`peng2022` | B；页级弱监督；训练开放缺口 | 作者仓库方法说明及引用条目；未阅读全文 |
| [A robust and efficient algorithm for Chinese historical document analysis and recognition](https://pmc.ncbi.nlm.nih.gov/articles/PMC10246825/)，National Science Review，2023；索引 ID：`liu2023` | B；多方向检测、双路径识别、裁切校正与顺序 | 公开全文已读 |
| [Reading between the Lines: Image-Based Order Detection in OCR for Chinese Historical Documents](https://doi.org/10.1609/aaai.v38i21.30572)，AAAI，2024；索引 ID：`ma2024` | A；独立阅读顺序学习与 HanDoc 模块 | 作者仓库及Crossref论文摘要；出版网页自动读取受限 |
| [HierCode: A lightweight hierarchical codebook for zero-shot Chinese text recognition](https://arxiv.org/abs/2403.13761)，Pattern Recognition，2025；索引 ID：`zhang2025` | B；部件／层次码本与未见字，非现成整页系统 | arXiv API摘要及Crossref书目；未确认官方代码 |

### 文档 VLM 与训练／部署

| 论文与出版信息 | 优先级／阅读目的 | 已完成核查 |
| --- | --- | --- |
| [dots.ocr: Multilingual Document Layout Parsing in a Single Vision-Language Model](https://arxiv.org/abs/2512.02498)，arXiv，2025；索引 ID：`li2025_dots` | B；版式、文本、阅读关系联合解析 | arXiv书目摘要及官方仓库 |
| [Multimodal OCR: Parse Anything from Documents](https://arxiv.org/abs/2603.13032)，arXiv，2026；索引 ID：`zheng2026_mocr` | B；文本与图形结构化、SVG，需固定模型版本 | arXiv书目摘要及官方仓库 |
| [HunyuanOCR-1.5: Making Lightweight OCR VLMs Faster and Better](https://arxiv.org/abs/2607.04884)，arXiv，2026；索引 ID：`li2026_hunyuan15` | B；Agentic Data Flow、DFlash、微调和部署 | 论文HTML v3的方法/实验/推荐提示与官方仓库已读 |
| [OvisOCR2 Technical Report](https://arxiv.org/abs/2607.13639)，arXiv，2026；索引 ID：`lu2026_ovis2` | B；真实／合成数据、4B→0.8B 蒸馏与退化评测 | 论文HTML v1的数据/训练/评测与模型卡已读 |
| [OvisOCR3 Technical Report](https://arxiv.org/abs/2610.33066)，arXiv，2026；索引 ID：`ovisocr3_2026` | B；新版 JSON／布局／OCR 框等能力；待全文阅读 | 论文书目摘要、模型卡已读；未阅读全文 |

### PaddleOCR 工程演进

| 论文与出版信息 | 优先级／阅读目的 | 已完成核查 |
| --- | --- | --- |
| [PP-OCR: A Practical Ultra Lightweight OCR System](https://arxiv.org/abs/2009.09941)，arXiv，2020；索引 ID：`ppocr2020` | C；轻量检测与识别的工程起点 | arXiv书目摘要已核对；未阅读全文 |
| [PP-OCRv2: Bag of Tricks for Ultra Lightweight OCR System](https://arxiv.org/abs/2109.03144)，arXiv，2021；索引 ID：`ppocrv2_2021` | C；轻量系统的训练与工程改进 | arXiv书目摘要已核对；未阅读全文 |
| [PP-OCRv3: More Attempts for the Improvement of Ultra Lightweight OCR System](https://arxiv.org/abs/2206.03001)，arXiv，2022；索引 ID：`ppocrv3_2022` | C；检测识别训练方法演进 | arXiv书目摘要已核对；未阅读全文 |
| [PP-StructureV2: A Stronger Document Analysis System](https://arxiv.org/abs/2210.05391)，arXiv，2022；索引 ID：`ppstructurev2_2022` | C；通用文档布局与结构恢复 | arXiv书目摘要已核对；未阅读全文 |
| [PaddleOCR 3.0 Technical Report](https://arxiv.org/abs/2507.05595)，arXiv，2025；索引 ID：`paddleocr3_2025` | B；PP-OCRv5／PP-StructureV3／PP-ChatOCRv4 分工 | arXiv书目摘要及官方项目说明；未阅读全文 |
| [PP-OCRv5: A Specialized 5M-Parameter Model Rivaling Billion-Parameter Vision-Language Models on OCR Tasks](https://arxiv.org/abs/2603.24373)，arXiv，2026；索引 ID：`ppocrv5_2026` | B；小型识别模型与 VLM 的任务、输入差异 | arXiv当前标题与摘要已核对，微信标题表述不同；未阅读全文 |
| [PaddleOCR-VL: Boosting Multilingual Document Parsing via a 0.9B Ultra-Compact Vision-Language Model](https://arxiv.org/abs/2510.14528)，arXiv，2025；索引 ID：`paddleocrvl_2025` | B；0.9B 文档 VLM 路线；与当前 1.6 区分 | arXiv书目摘要已核对；未阅读全文 |

PP-OCRv5 当前 arXiv 题名与微信综述中的旧表述不同，本页采用当前已核对题名。AncientDoc 为 2025 预印本／2026 Findings ACL；OvisOCR3 是文章发表后追踪到的新版本。动态仓库文档不应当作旧模型的冻结复现说明。

## 二、用户提供入口与文章追踪

| 原始入口 | 对应内容 | 当前综合报告中的位置 |
| --- | --- | --- |
| [古籍酷博客](https://ocr.gj.cool/blog) | 下列 8 篇技术／工作流文章与 [API 文档](https://ocr.gj.cool/doc/v1) | [服务与工程经验](README.md#workflows)、[性能证据](README.md#performance)、[AncientDoc 核查](README.md#audits) |
| [IEEE 8364534](https://ieeexplore.ieee.org/document/8364534/) | RGD 2018，正式 DOI：10.1109/ACCESS.2018.2840218 | [关键论文方法](README.md#methods) |

<a id="wechat-articles"></a>
### 七篇微信文章

七篇正文均在此前调研中读到，并追踪其作者仓库、模型卡或论文。下列标题保留原文；“首款”“免费”等属于文章措辞，核查结论见综合报告，不视为本报告背书。

| 文章／用户链接 | 日期、作者 | 对应资源与阅读价值 |
| --- | --- | --- |
| [首款纯本地的古籍OCR来了，绿色免安装，功能全免费！](https://mp.weixin.qq.com/s/NAWJJ5gBssbA2SBY5qHrbw) | 2026-09-29，游氏古籍研究室转经世国学馆／耕田四哥 | 软件说明；免费不等于开源，官网限非商业个人研究；资源 ID：`gujiyun_ocr` |
| [dots.mocr｜古籍 OCR 开源项目观察之四](https://mp.weixin.qq.com/s/aUdOM5Puffl2Ywx_EqztHg) | 2026-08-02，数字人文港 | 11页测试，报告CER8.9%；未找到完整dots输出和评分脚本；资源 ID：`dots_mocr`、`ancientdoc_ocr_mini` |
| [PaddleOCR 简史：古籍 OCR 开源项目观察之一](https://mp.weixin.qq.com/s/2_yPxPw78Ak4ueAfxbj69Q) | 2026-07-07，数字人文港 | 技术综述；没有新增古籍受控实验；资源 ID：`paddleocr` |
| [dots.ocr｜古籍 OCR 开源项目观察之二](https://mp.weixin.qq.com/s/KUR7vrLD-Qg99ViBIq-71g) | 2026-07-08，数字人文港 | 结构化文档解析路线介绍；资源 ID：`dots_ocr`、`dots_mocr` |
| [HunyuanOCR-1.5｜古籍 OCR 开源项目观察之三](https://mp.weixin.qq.com/s/IsyXcdEkC4KMj0tVOpvmhA) | 2026-07-15，数字人文港 | 原论文和训练入口已追踪，须补充自定义许可限制；资源 ID：`hunyuan_ocr15`、`chronicles_ocr` |
| [OvisOCR2｜古籍 OCR 开源项目观察之五](https://mp.weixin.qq.com/s/DdwTjSbrRF9c5IcHVKcI8Q) | 2026-08-06，数字人文港 | 通用文档成绩不等于古籍专项；本次发现后续OvisOCR3；资源 ID：`ovisocr2`、`ovisocr3` |
| [【论文解读】古汉字识别新基准 ｜ 腾讯混元发布Chronicles-OCR](https://mp.weixin.qq.com/s/gTfVVP4D8xWj3NPs3w4JIA) | 2026-06-05，FireAICV | 七书体扩展评测；指标已用原文和代码校正；资源 ID：`chronicles_ocr`、`chronicles_eval` |

其中 dots.mocr 文章的 11 页实验没有发现完整逐页输出和评分脚本；其公开 notebook 的问题不证明文章作者使用了相同流程。混元、Ovis、Chronicles 的原始资料已在文章发表后更新，需以具体版本区分。

<a id="gj-articles"></a>
### 古籍酷八篇文章

| 文章 | 日期 | 阅读重点与证据边界 |
| --- | --- | --- |
| [排版引擎大更新：古籍酷排版2.0技术详解](https://ocr.gj.cool/article/2026-10-16-new-layout-engine) | 2026-10-16 | 区域归属、大小字、行字坐标与夹注局部结构；产品技术说明，未公开完整引擎 |
| [开源OCR大模型的“冰与火”](https://ocr.gj.cool/article/2026-04-03-ocr-model) | 2026-04-03 | 夹注分层、竖排顺序、失败与耗时；厂商自测，缺少完整测试集及计分规范 |
| [大模型——大跃进？大泡沫？](https://ocr.gj.cool/article/2026-02-04-ancient-doc-criticize) | 2026-02-04 | 可检查的 AncientDoc 问题样例；不能把输出差异当全库标签错误率 |
| [速度与激情：2026春季技术报告](https://ocr.gj.cool/article/2026-03-15-gjcool-report) | 2026-03-15 | CNN→ViT 条件级联、推理与纠错；速度和准确率为厂商自报 |
| [打通OCR与自动标点最后“一公里”](https://ocr.gj.cool/article/2026-06-16-punct-progress) | 2026-06-16 | 跨行标点、保留换行和字符跳过规则；下游整理应与原始转写分离 |
| [古籍和老旧报刊整理之利器](https://ocr.gj.cool/article/2025-12-02-old-newspaper) | 2025-12-02 | 图文校对、不确定字、批处理；使用案例不是受控性能实验 |
| [古籍OCR新版发布](https://ocr.gj.cool/article/2025-04-01-ocr-new-version) | 2025-04-01 | 早期版本、生僻异体字、API；不能代表当前统一版本成绩 |
| [科判制作](https://ocr.gj.cool/article/2025-10-26-htree-edit) | 2025-10-26 | 科判层级数据编辑；人工结构整理，不是自动识别算法 |

## 三、代码、模型与数据入口

综合报告已按任务分组列出全部资源，避免在本页重复维护模型能力和许可：

- [13 项数据资源：标注、规模、获取与重叠关系](README.md#datasets)。
- [16 项代码／模型／评测工具：输出、训练和复现边界](README.md#tools)。
- [古籍酷服务与古籍云桌面工作流](README.md#workflows)。
- [机器可读资源索引](resources.json)：稳定 `id`、`tasks`、`urls`、`license`、`verification`、`notes`、`checked_at`；论文与文章通过 `related_resource_ids` 关联资源。

## 四、历史参考与核查文件

三份旧报告保持原文与原路径，保留细节和当时论述；日常阅读以新综合报告为主：

- [中文竖排古籍 OCR 首轮调研](2026-11-11-中文竖排古籍OCR调研.md)。
- [古籍酷、RGD 与 AncientDoc 补充调研](2026-11-11-古籍酷与RGD论文补充调研.md)。
- [七篇微信资料追踪](2026-11-11-微信七篇古籍OCR资料追踪.md)。
- [核查证据说明与文件](evidence/README.md)：计数、哈希、方法与限制。

资源索引的 `report` 指向新综合报告，`reference_reports` 列出三份旧报告；`supplementary_reports` 保留原有两篇补充报告字段，兼容原先的引用。新增实验应补充日期和版本证据，避免将未运行模型的资料调研改写成性能实测。
