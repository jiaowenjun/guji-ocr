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

解析器、CodeMirror 编辑器与 guji-preview 完全一致；应用外壳已分叉——本项目自
2026-11-12 起移除独立「编辑」双栏模式，打开即数据集对照视图（通用编辑/预览用 guji-preview）。

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

- **Safari 本机字体匹配**：WebKit 对这批用户字体（康熙傳承版/中华书局宋体）的
  `local()` 会「解析成功但渲染不可用」（伪命中，还会挡住 src 后续来源），font-family
  写注册名也不匹配；Chrome 一切正常。修复：`@font-face` 以 **url() 为首源**加载随仓库
  入库的 `public/fonts/*.ttf`（guji-large 45M = kangxizidian.com 康熙傳承版；
  guji-plane0/2/f 18M+41M+25M = 中华书局宋体 00/02/15 平面，版权归原发行方，限研究用途），
  任何浏览器与服务器部署渲染一致；`local()` 名字链退居其次仅作文件缺失时的 Chrome 兜底。
  Playwright WebKit 像素级验证：url 优先渲染真字形，local 优先渲染回退 serif。
  编辑器 `.cm-scroller` 字体栈同样接入三平面（拉丁/符号仍等宽），扩展 B/C 区字符不再缺字
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

- **编辑器 ↔ 渲染列联动**：光标所在**大行**琥珀高亮（间隙取前行）；光标落在
  **书名区间**内时两侧书名框同时点亮（含跨大行 wrap，如【史記·儒/林傳】）；
  点击渲染列任意行 → 编辑器光标跳到该行源码首位。定位器 `src/parser/locate.ts`
  独立复刻分块语义（不动被 fixtures 锁定的解析器），对等性测试锁定（41 例）
- 打开即**数据集对照**视图（原「编辑」双栏模式已移除）：kangxi-gold 金标三列
  可视化与校对（见下节），含矩阵/Flex 渲染切换与界栏开关（矩阵视图）
- **亮/暗主题**：默认跟随系统（`prefers-color-scheme`），顶栏可手动三态切换
  （跟随系统/浅色/深色，localStorage 持久化）；语法高亮配色经 CSS 变量随主题切换，
  刻本纸面与扫描图保持原色不反色

## 数据集对照模式

顶部「编辑 / 数据集对照」切换。数据集模式为三列布局：**扫描原图 | 刻本渲染 | .gj 编辑器**，
用于目视核对 [kangxi-gold](../kangxi-gold/README.md) 金标与后续扩页校对：

- 渲染列内容与原图**版框**对齐：外包与扫描同尺寸的纸层（等比纸边
  `SCAN_FRAME_MARGIN`，17 页投影法实测；纸面色 #dcb68a），`unit = (版框宽−2px)/横向字格数`；
  默认 **Flex 视图 + 界栏关 + 原图高度适配视口**（缩放滑杆切为宽度百分比，↺ 恢复适配）。
  矩阵视图像素级对齐，Flex 视图行宽按内容混合为近似
- ←/→ 翻页（编辑器聚焦时不劫持）；未保存修改按页保留，切页/切模式不丢
- **「添加新页」**：输入页码（1–7738）→ `scripts/kangxi_page_tool.py` 补数据
  （sqlite `datasets/kangxi-crawl.sqlite3` 已有则零联网，缺则由 fetch_kangxi_page/
  fetch_kangxi_entry 增量爬取）→ 由 page_chars + entries 生成 .gj 草稿（字头行 +
  释义段落带，未编码字 `#□` 占位注释）入 `annotations/`、manifest 追加该页并刷新
  index.json，前端自动跳转；`POST /dataset/page-tool` 中间件仅 dev 生效
- **页标签**：草稿（爬取生成）/ 初校 / 精校，存 manifest.json 每页 `status` 字段，
  工具条徽章与页清单均带标记；既有 17 页定为初校
- 「保存回数据集」写回 `kangxi-gold/annotations/NNNN.gj`（仅 dev server 生效的
  `POST /dataset/save` 中间件，vite.config.ts；校验页码在库内且首行仍为 @页码）
- 保存后同步 json/txt：`npx -y tsx kangxi-gold/scripts/build_annotations.ts --allow-drift`
  （默认严格模式会因与原 fixture 不一致而拒绝，属预期防呆；样例外的附加页两种模式
  都会从其 .gj 生成 json/txt）

首次使用先生成数据集访问层（符号链接，已 gitignore，重跑安全）；刻本字体文件
已随仓库入库（`public/fonts/`，~129MB，无需额外步骤）：

```sh
bash scripts/link-dataset.sh   # 需挂载存放扫描图的外置盘（manifest.images_dir）
```

Guji 语法、字体安装说明见 [guji-preview README](../guji-preview/README.md)。
