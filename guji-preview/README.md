# guji-preview

古籍（`.gj`）编辑与仿刻本预览的 Web 应用，由 VS Code 插件
[vscode-guji-preview](../vscode-guji-preview) 移植而来（原插件保留不动）。

技术栈：Vite + React + TypeScript + TailwindCSS v4 + shadcn/ui + CodeMirror 6。

## 功能

- 左侧 `.gj` 编辑器（CodeMirror 6，Guji 语法高亮），右侧刻本渲染实时预览（防抖 200ms）
- 多页文档（多个 `@页码` 声明）纵向长滚动展示，分栏可拖拽调节
- 缩放滑块（12–48px，控制刻本渲染基准字号）
- 内置示例（《康熙字典》三一二页单页示例、子集上一部 17 页多页示例）、打开本地 `.gj` 文件
- 导出自包含 HTML（样式内联、无外部依赖，与原插件 Webview 产物同构）
- 解析器与原插件逐字等价（`pnpm test` 内含由原插件解析器生成的 fixture 严格比对）

## 开发

```sh
pnpm install
pnpm dev      # 开发服务器
pnpm test     # 解析器测试（vitest）
pnpm build    # 类型检查 + 构建
```

## Guji 語法

|    特殊符號    |    作用範圍    |         含義         |
| :------------: | :------------: | :------------------: |
| `//`_comment_  |     至行尾     |        行注釋        |
|    `@`_num_    |     至行尾     |     指定當前頁數     |
|     `空行`     |                |       大行換行       |
|     `EOF`      |                |       大行換行       |
|   `#␣`_text_   |     至行尾     |       一行大字       |
|  `##␣`_text_   |     至行尾     |   一行大字縮進一格   |
|  `###␣`_text_  |     至行尾     |   一行大字縮進兩格   |
|  `↵` (換行符)  |                |       小行換行       |
|   `#`_char_    |   後一個字符   |    行內的一個大字    |
|   `#(`_char_   |   後一個字符   |  行內的一個帶圈大字  |
| `#(`_A_ _B_`)` | 括號內兩個字符 | 兩字合成一個帶圈大字 |
| `【`_text_`】` |   括號內文本   |       行內書名       |
| `【`_text_`↵`  |   括號至行尾   |      行內半書名      |
| `^`_text_`】`  |   行首至括號   |      行內半書名      |
|      `*`       |                |       行內空格       |

> 注：实际语料中单字带圈大字写作 `#(一`（不闭合，后接下一个 `#` 标记），
> 两字合成的带圈大字写作 `#(十五)`。

## 字體安裝

刻本渲染依赖本地安装的两款字体（未安装时以 serif 回退显示，版式不变）：

- 大字字體：
  - 字體名： `康熙傳承版 KangXiZiDian.com`
  - 官網鏈接： [官網](https://www.chinesecj.com/forum/forum.php?mod=viewthread&tid=195626)
- 小字字體（內含三種字體）：
  - `中華書局宋體00平面` / `中華書局宋體02平面` / `中華書局宋體15平面`
  - 官網鏈接： [官網](https://www.ancientbooks.cn/helpcore?font)

## 目录结构

```
src/
├── parser/            # 解析器：.gj 文本 → PageModel[]（移植自原插件，行为一致）
├── components/
│   ├── guji/          # 刻本渲染组件（DOM 结构与 class 名与原插件一致）
│   ├── editor/        # CodeMirror 6 编辑器 + Guji 语法（移植自 tmLanguage）
│   └── ui/            # shadcn/ui 组件
├── guji.css           # 刻本渲染样式（移植自原插件 html.ts 内联样式）
├── samples/           # 内置示例 .gj
└── hooks/ lib/
test/                  # vitest：解析器行为契约 + 与原插件输出的严格比对
```
