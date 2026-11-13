# 文档导航

本仓库包含中文竖排古籍 OCR 调研，以及独立的古籍文本编辑／排版预览应用。当前 OCR 部分仍处于资料与方案阶段，尚无本仓库的模型性能复现实验。

## 从哪里开始

| 需求 | 文档 |
| --- | --- |
| 完整了解调研结论、资源、技术路线与评测方案 | [中文竖排古籍 OCR 综合调研报告](research/README.md) |
| 查论文题名、原始链接、阅读深度或用户提供的文章 | [参考文献与来源](research/references.md) |
| 按任务、许可、资源 ID 继续筛选或编写脚本 | [机器可读资源索引](research/resources.json) |
| 检查 AncientDoc、Chronicles 和 11 页样本的具体核查依据 | [证据目录说明](research/evidence/README.md) |
| 使用 `.gj` 流式排版预览 | [guji-preview 使用与开发说明](../guji-preview/README.md) |
| 使用字格矩阵排版和两种渲染对照 | [guji-preview-grid 使用与开发说明](../guji-preview-grid/README.md) |
| 核验康熙字典未编码字头（K0000）与字体缺字判定 | [未编码字头字体核验流程](research/2026-11-13-kangxi-未编码字头字体核验流程.md) |
| 向康熙字典體补录缺字字形（K0000 字形入库） | [字体补录流程](research/2026-11-13-kangxi-字体补录流程.md) |

## 文档结构

```text
README.md                              仓库入口
docs/
├── README.md                          本导航
└── research/
    ├── README.md                      新综合报告，主要阅读入口
    ├── references.md                  论文与文章来源索引
    ├── resources.json                 结构化资源清单
    ├── evidence/
    │   ├── README.md                  核查方法、文件与证据边界
    │   ├── 2026-11-11-ancientdoc-spotcheck.json
    │   ├── 2026-11-11-wechat-source-checks.json
    │   ├── 2026-11-12-kangxizidian-site-structure.json
    │   └── 2026-11-13-kangxi-unencoded-0334-04-fontcheck.json
    ├── 2026-11-11-中文竖排古籍OCR调研.md             历史参考
    ├── 2026-11-11-古籍酷与RGD论文补充调研.md        历史参考
    ├── 2026-11-11-微信七篇古籍OCR资料追踪.md         历史参考
    ├── 2026-11-12-kangxizidian-网站结构调研.md      字头索引与抓取可行性
    ├── 2026-11-13-kangxi-未编码字头字体核验流程.md  K0000 身份判定与缺字判定
    └── 2026-11-13-kangxi-字体补录流程.md           K0000 缺字字形入库操作手册
guji-preview/README.md                  流式预览应用文档
guji-preview-grid/README.md             字格预览应用文档
```

结构按“综合结论—来源索引—核查证据—历史参考”组织。旧报告保留原路径和原文，以免破坏已有引用；各应用的使用说明继续由应用自身维护。

## 历史参考报告

| 报告 | 内容 |
| --- | --- |
| [首轮调研及当时补充](research/2026-11-11-中文竖排古籍OCR调研.md) | 论文、项目、数据集及初步选型 |
| [古籍酷与 RGD 补充](research/2026-11-11-古籍酷与RGD论文补充调研.md) | 8 篇博客、API、RGD 全文和 AncientDoc 定向核查 |
| [七篇微信资料追踪](research/2026-11-11-微信七篇古籍OCR资料追踪.md) | 古籍云、dots、Hunyuan、Ovis、Chronicles 及样本评分代码 |

新增实验记录应标明日期、样本及模型版本，记录运行结果与失败情况；方案建议与已验证行为分开。综合报告与资源索引可随新证据更新，历史报告保持快照语义。
