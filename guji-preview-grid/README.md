# guji-preview-grid

以 **CSS Grid 字格矩阵**重构古籍刻本渲染层的实验性 Web 应用，姊妹项目：
[guji-preview](../guji-preview)（flex 流式渲染，保持不动）。

## 与 guji-preview 的差异

| | guji-preview（flex） | guji-preview-grid（本项目） |
|---|---|---|
| 布局模型 | 流式：`row-reverse` flex，行对齐由内容"涌现" | 严格矩阵：布局引擎推导 1em 字格坐标，显式 grid 轨道 |
| 跨行书名 | `book-start/middle/end` 三态 + 负边距阶梯 + `:has()` 按边删 border 拼接 | 同列连续片段合并为**单个跨行矩形项**（单一边框）；仅 wrap 连接边开口 |
| 行线贯通 | 无（仅外框） | 大行之间界栏全页高（`border-left` + subgrid 占满行，可开关） |
| 渲染管线 | `parsePages → React 组件` | `parsePages → layoutPages（坐标推导）→ 矩阵组件` |

解析器、CodeMirror 编辑器、应用外壳与 guji-preview 完全一致（本目录为完整拷贝）。

## 架构

```
.gj 文本 → parser（与原插件逐字等价，测试锁定）
         → layoutPages 布局引擎（src/matrix/layout.ts）
           · 段流划分复刻 flex 版 Line.tsx 的 parseLineBlocks 分组算法
           · band（大行）局部坐标：大字/带圈 2×2，小字 1×1
           · 小行 0 在最右（row-reverse 语义）；小字组在 band 内居中取整
           · 书名合并：同小行内连续 book 片段 → 单一边框项，open 标记 wrap 开口
         → MatrixPages 组件
           · 页 = 显式轨道 grid（repeat N × 1em，轨道数由引擎给出）
           · band = subgrid 项占满整页高 → border-left 即贯通界栏
           · band 0 放最右列；触及版框的书名项 margin 共线
```

## 已知偏差与兼容性

- **亚格取整**：flex 版小字组为 auto-margin 精确居中，`W−k` 为奇数时落 0.5em；
  矩阵版取整。语料中夹注恒为双行（k=2，W=2），实际不触发
- **续书名并列**：解析器在续书名状态遇换行不产出 br，【字/彙/补】实际渲染为
  两列（`字` + `彙补` 合并）——矩阵版照实复刻 flex 既有行为
- **subgrid**：需 Chrome 117+ / Safari 16+ / Firefox 71+（2023 起 baseline）；
  导出的独立 HTML 同样依赖

## 开发

```sh
pnpm install
pnpm dev      # 开发服务器
pnpm test     # 32 个测试：parser 19（与原插件 fixture 严格比对）+ 矩阵引擎 13
pnpm build
```

## 功能

- 「矩阵 / Flex 对照」视图切换：同一文档两种渲染即时对照
- 界栏开关（矩阵视图，默认开）
- **「数据集对照」模式**：kangxi-gold 金标三列可视化（见下节）
- 其余（编辑器、示例、缩放、导入导出）与 guji-preview 相同

## 数据集对照模式

顶部「编辑 / 数据集对照」切换。数据集模式为三列布局：**扫描原图 | 刻本渲染 | .gj 编辑器**，
用于目视核对 [kangxi-gold](../kangxi-gold/README.md) 金标与后续扩页校对：

- 渲染列宽度跟随原图列显示宽（`unit = (显示宽−2px)/横向字格数`），逐字对照像素对齐
- ←/→ 翻页（编辑器聚焦时不劫持）；未保存修改按页保留，切页/切模式不丢
- 「保存回数据集」写回 `kangxi-gold/annotations/NNNN.gj`（仅 dev server 生效的
  `POST /dataset/save` 中间件，vite.config.ts；校验页码在库内且首行仍为 @页码）
- 保存后同步 json/txt：`npx -y tsx kangxi-gold/scripts/build_annotations.ts --allow-drift`
  （默认严格模式会因与原 fixture 不一致而拒绝，属预期防呆）

首次使用先生成数据集访问层（符号链接 + 页清单，已 gitignore，重跑安全）：

```sh
bash scripts/link-dataset.sh   # 需挂载存放扫描图的外置盘（manifest.images_dir）
```

Guji 语法、字体安装说明见 [guji-preview README](../guji-preview/README.md)。
