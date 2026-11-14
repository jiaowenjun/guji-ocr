# guji-ocr

中文竖排古籍 OCR 调研、后续实验与古籍文本排版预览工作区。

## 调研文档

从 **[中文竖排古籍 OCR 综合调研报告](docs/research/README.md)** 开始：整合全部已调研资料，覆盖文字识别、物理／语义版式、阅读顺序、模型与数据、核查结果、选型、架构和评测方案。资料核查截至 2026-11-11。

- [文档导航与目录结构](docs/README.md)
- [参考文献与来源：27 篇论文、15 篇文章及用户链接](docs/research/references.md)
- [机器可读资源索引](docs/research/resources.json)
- [文件核查证据与适用边界](docs/research/evidence/README.md)

索引另含 13 项数据资源、16 项代码／模型／评测工具，以及古籍酷服务、古籍云桌面软件。数据资源包含派生教学样本，不代表 13 个独立金标库。三份旧报告保留原文和原路径，作为[历史参考](docs/README.md#历史参考报告)。

OCR 部分尚未安装、运行模型或复现性能；报告中的性能数字来自相应作者／文章，文件核查与待实施方案分别标明。

## OCR 基线服务

| 服务 | 用途 |
| --- | --- |
| [paddleocr-baseline](paddleocr-baseline/README.md) | 本地 PaddleOCR（PaddleOCR-VL-1.6）异步 job 服务与批量 CLI，为古籍 OCR 提供可对照的工程基线 |

## 自建金标数据集

| 数据集 | 用途 |
| --- | --- |
| [kangxi-gold](kangxi-gold/README.md) | 康熙字典武英殿版 17 页（@312–@328）整页文本金标 v1：`.gj`/JSON/阅读序 TXT 三件套 + 严格 CER 评测脚本；图片存 WD-2T，清单带 sha256 |

## 古籍预览应用

| 应用 | 用途 |
| --- | --- |
| [guji-preview-grid](guji-preview-grid/README.md) | 字格矩阵刻本渲染 + kangxi-gold 数据集对照校对，Guji IR v3 与 `.gj` 语法定义所在 |

预览应用承接文本编辑与排版展示；OCR、源图定位和自动版式识别仍属于后续工作。
