# Guji IR（.gj ↔ 渲染的中间表示）设计

状态：**v3 已实现，当前输入语法为 .gj/2**（见 §10；§1–9 为设计沿革）

历史状态：**v3 已实现**（骨架/overlay 双层，破坏性替换 v2/v1 内部模型；
TXT/评测口径在 18 页语料上逐字符一致）。本文含 v1/v2 沿革与 v3 决策。代码在
`guji-preview-grid/src/ir/`（`types.ts`、`gj2ir.ts`、`ir2blocks.ts`、
`text.ts`、`linkage.ts`）。本文含 v1 设计沿革与 v2 升级决策。

## 1. 动机（v1 沿革）

此前三套各自独立消费 .gj 的逻辑（解析器、矩阵布局引擎、联动定位器 locate.ts）
存在漂移面；且被 fixture 锁定的解析器在解析时**丢弃标点**（信息不可逆），
书名以 `book-start/middle/end` 三态碎片表达（wrap 是版面概念却混入了语义层）。
IR 把这三件事收拢：

| 收益 | 实现 |
| --- | --- |
| 书名语义统一 | 一个书名一个元素，`parts[].band` 显式表达跨大行物理分布 |
| 保真层级分离 | IR 保留标点/折行/注释剔除边界；剔除规则归 profile（渲染/评测共用） |
| 稳定 id + 源偏移 | 编辑器联动查 `src` 区间（locate.ts 退役）；OCR 对齐/坐标可挂靠 |
| 多源输入 | 渲染器只认 IR；爬取草稿、PAGE XML、OCR 输出皆可产出 IR |

## 2. Schema（v1）

```jsonc
{
  "version": 1,
  "meta": {
    "sourceFormat": "gj", "generatedBy": "guji-ir/1", "fidelity": "full",
    "profile": { "stripPunct": ["。，·\":：、《》"], "normalize": [["◎","○"],["〇","○"]] }
  },
  "pages": [{
    "id": "p0312", "no": 312, "src": [3, 8],
    "bands": [{
      "id": "p0312-b2", "ord": 2,
      "heading": { "level": 3, "text": "一部" },   // #/##/### 标题大行；正文大行无此字段
      "src": [16, 25],
      "segments": [                                  // 扁平有序段流（渲染顺序）
        { "kind": "head",   "id": "…-s0", "char": "一" },
        { "kind": "text",   "id": "…-s1", "text": "於悉切，𠀤漪入聲。" },  // 标点保留
        { "kind": "book",   "id": "…-s2", "src": [30, 48],
          "parts": [ { "text": "史記·儒" }, { "text": "林傳", "band": "p0312-b4" } ] },
        { "kind": "mark",   "id": "…-s3", "text": "增", "style": "circled" },
        { "kind": "br" }
      ]
    }]
  }]
}
```

关键决策：

1. **段扁平有序**：渲染按序消费、OCR 按序对齐、联动按段定位
2. **`book.parts`**：语义一个书名；延续行 part 的 `band` 指向目标行（延续段
   始终位于行首——与解析器孤儿 `】` 语义一致）
3. **保真**：text 段保留标点与空格（含字面 `*` 变来的尾随空格）；`br` 保留
   原文折行；剔除/归一在 `meta.profile`，渲染与评测同源
4. **kind 封闭于 .gj 可表达范围**：head / text / book / mark(circled) / br +
   band 级 heading；不发明反切、义项等解释性结构
5. **src 可选**：原始文本偏移（`.gj` 来源时存在；其它来源可缺省，联动降级）

## 3. 对等性契约（防漂移的核心）

- `ir2blocks(gj2ir(t)) === parsePages(t)`：全语料（17 页样例、330 校对草稿、
  8 组合成边界用例）逐字符锁定（`test/ir.spec.ts`）
- `irPageToText(gj2ir(t)) === pageToText(parsePages(t))`：金标 txt 同源断言，
  `build_annotations.ts` 每次构建**运行时强制**（不等即拒绝产出）
- `eval_cer.py --from-ir` 的 Python 抽取与 txt 逐页逐字符相等（18 页验证）

## 4. 管线（P1–P3 落地后）

```
.gj ──gj2ir──▶ IR（语义，保真+profile）
                 ├─ir2blocks──▶ PageModel ──layoutPages──▶ 矩阵/Flex 渲染（零改动）
                 ├─irPageToText──▶ NNNN.txt（金标阅读序文本）
                 └─highlightAt/bandCursorTarget──▶ 编辑器↔渲染联动（替代 locate.ts）
金标 NNNN.json = 单页 IR 文档；manifest.annotations_schema = "guji-ir/1"
```

## 5. 实现勘误（词法镜像中踩过的坑）

- 字面 `*`（由全角空格变换而来）经 parser 语义会成为**尾随空格**保留在块文本中
  ——IR 词法消费 `lineTransform` 后的文本（与 parser 输入同层），空格规则天然一致
- `#` 后跟 `　`（→`*`→空格）仍是合法大字（`{t:" "}`）
- `#(` 带圈双前瞻按 code unit（`line.at(i+2)/(i+3) === ")"`），镜像时不可改码点视角
- 延续行的书名段是行内第 0 个书名块（孤儿 `】` 语义），跨行 parts 装配按全文
  原始偏移配对，与行内词法解耦

## 6. v2：面向 OCR 版式分析与古籍排版的层级化升级

评估结论（2026-11-13）：v1 的扁平段流对"读文本"足够，但对**行级 GT 可寻址**
（OCR 行检测/IoU 评测）、**版式元素分类**（大字/小字）与**跨行语义精确引用**表
达不足。v2 按「物理层级 + 语义 overlay」重构（与 PAGE XML 的 region→line→word
+ 结构链接同范式）：

### 结构

```
page
 └ band（大行）
    ├ heading?（#/##/### 标题大行；不物化为小行）
    └ lines[]（小行 = .gj 内一条物理折行；换行是一等公民，带 id + src）
        └ elements[]：{ class: large|small（版式轴），sem: head|gloss|title|mark（逻辑轴），
                        text（保真），style?（circled），ref?（书名 overlay 引用） }
 semantics.books[]（页级跨行语义 overlay）
   = { id, src（原始区间含【】）, spans: [{ line（行 id）, range（行规范文本内字符区间）}] }
```

### 相对 v1 的变化

| 维度 | v1 | v2 |
| --- | --- | --- |
| 小行 | br 段标记隐式切分 | `lines[]` 结构单元（id/src/ord），行级 GT 可直接引用 |
| 元素 | kind 耦合版式与语义 | `class`（版式）× `sem`（逻辑）正交；OCR 标注常只需 class |
| 书名跨行 | parts[].band + part.text 内嵌 \n | 页级 overlay + 行内锚；spans 精确到（行, 行内区间） |
| meta | — | 增 `lineLayout: "fold"`（小行来源=转写折行）与 `orientation` |

### 兼容与对等

- 对等性契约不变：`ir2blocks(gj2ir(t)) === parsePages(t)`（18 页语料 + 8 合成例）
- `irPageToText` 输出与 v1 逐字符一致（金标 txt 不变；build 运行时断言沿用）
- 渲染联动接口（RenderHighlight/BookRuns）不变；linkage 数据源改为 band.src 与
  books overlay
- manifest `annotations_schema: guji-ir/2`；`eval_cer --from-ir` 与 txt 等价（18 页）

### v2 词法新增 quirk 记录

- 开启书名内的行边界：**首个**边界后出 br（parse-inline 的 book 态换行），其后
  边界不出（book-half 态）——ir2blocks 以「锚行序 ≥2 前的边界抑制」重建
- 行内可含多个书名锚（`【A】子【B】丑`）；锚↔区域映射在构建期记录（局部 Map）
- 同一原始 span 的开启/延续区域合并为**单一**书（按 span 键去重，开启行先到）

## 7. v3：骨架/overlay 双层（破坏性更新，替换内部模型）

外部评审修正了 v2 评估的两点：这不是字段迁移，也不能把「与旧解析器完全一致」
作为最高验收标准。核心原则改为：**骨架决定文本、占格与换行；overlay 描述附着
其上的样式或语义**——去掉全部 overlay 后，页面仍具有相同的阅读顺序、字格占用
与行边界。

### 结构

```
骨架（排版版式）                          overlay（文档级，单向引用）
page                                     overlays[]
 └ band（大行；level=标题层级元数据）        ├ { kind:"circle", target: 元素id }
    └ lines[]（小行=物理折行，带 src）        └ { kind:"book-title", spans:[{line, range}],
        └ elements                            src?（UTF-16，仅溯源/联动）}
           { class: large|small, text,
             ligature?（合字：n 字合占一个大字格）}
```

- 大字元素恰好占一个大字格；合字内部组合由骨架决定，圆圈只修饰该格
- 标题文字物化进骨架（逐字大字），层级为 band 元数据——文本只有一条存储路径
- 书名文字只存于骨架（并入相邻小字段，括号不产生骨架内容）；overlay 按行+码点
  区间单向引用；行内 range 一律码点半开区间（src 单位 UTF-16 单独声明）
- 主路径：输入 → 骨架 → layout3（字格布局+定位映射）→ 应用 overlay → 渲染；
  ir2blocks/book-start/middle/end 状态机全部退出；书名不再吞换行
  （【字↵彙↵補】三行三列，框以跨行矩形绘制）；渲染不依赖 src（无 .gj 源可用）

### 验收（v3 契约，取代旧解析器 parity）

- overlay/src 增删：pages 与 layout3 输出逐字节不变
- #(增 与 #增 骨架相同（圆圈纯样式）；【A】b 与 Ab 骨架相同（括号纯样式）
- #(十一)：一个大字格、文本两字符、圆圈为 overlay
- 跨行书名不吞换行；相邻书名各自身份；无 src 可布局渲染
- ext-B 按码点计（range 不切代理对）；TXT/CER 与旧口径逐字符一致（18 页语料）
- 旧解析器 fixture 契约保留在 parser.spec（解析器本身未动），但渲染主路径不再
  以其为验收标准

## 8. 字头簇糖（2026-11-14，词法扩展——IR 结构不变）

`.gj` 字头行的簇内 token 可省 `#`，「古文」标记两侧标点可省；标准形（formatGj 归一目标）：

```
#(五)#(增)#𠂂   ≡ #(五)(增)𠂂
#(三)#丹古文#𠁿#㣋 ≡ #(三)丹，古文：𠁿㣋   （糖可无标点；格式化补全 ，：）
```

语法单一事实源是 `parser/split-line.ts` 的**字头簇扫描器**（`scanHeadCluster`），五个消费者
共用：formatGj 归一/独占一行、字头条提取（headwords.ts）、编辑器语法高亮（guji-language.ts）、
康熙字体装饰（large-char-decoration.ts）；gj2ir 与 parse-inline 的词法各自镜像其规则
（build_annotations 的旧解析器 TXT 等价断言对糖文件保持绿）。

规则要点（防歧义的收窄设计，全部经 28 页金标 + 17 页样例扫描验证）：

- 带圈续写：`(` 紧随大字 token 即 `#(` 的省 `#` 形——语料中 `(` 从不出现在小字正文
- 裸字大写在任意大字 token 后（@340 `#丶#宔` ≡ `#丶宔` 字头连写串；带圈后一字、
  `古文` 标记或 `、` 后为变体连串）；`、` 紧随大字/变体链开启变体语境。
  「古」与半角 `:` 不参与裸写（标记首字/跨行半个标记/尾注音冒号）——全语料
  `#X` 后紧邻内容字经 isBareLargeChar 实判重扫仅「古」一类
- `古文` 标记仅认「紧邻大字 token」（`，?古文[:：]?`）与行首带冒号承接形（`古文：`）；
  `#丅【字彙補】古文下`（书名隔开）与折行产生的行首 `古文酉`（无冒号）均不误判
- 标记两侧 `，：` 是小字内容（原书无标点，属转写层）——糖与长式的骨架差异仅此，
  TXT（profile 剔除）与 layout3 占格完全一致；圆圈 overlay 数目一致

对等性契约相应扩展（`test/ir.spec.ts` v3 字头簇糖）：13 对糖↔长式在
「清洗口径骨架（去 src/cpSrcs）+ layout3（去码点偏移）+ TXT + 圆圈数」四维等价；
formatGj 全语料不变量的字符流改为 profile 清洗口径（格式化会补 `，古文：` 标点）。
Python 侧（kangxi_page_tool.py）宿主识别正则 `#(?:圈)*頭` 与剥尾正则同步支持糖
（`#` 式旧形与旧正则零行为差异）。既有金标零迁移：糖是增量语法，仅在
格式化或新录入时逐步进入语料。


## 9. v3 契约优化（2026-11-16）

持久化仍为 v3；已有 45 页 JSON 无需迁移。用户修复的 318／320／322／325／327
分段均已同步派生文件，当前合计 360 band、每页 8 band、页宽 16 格、页高 24 格。

- **清洗**：`compileProfile` 编译文档 `meta.profile`，文本导出与布局共用；Python
  也按规则数组顺序执行（不先转成字典去重）。剔除项限定单码点，归一化不允许空匹配。
  `rawRanges[k]` 记录第 k 个显示码点对应的原始码点半开区间，`rawOffsets` 保留首偏移兼容。
  跨元素归一化不执行，与既有逐元素文本导出口径一致。
- **版式**：可选 `meta.layout = { version: 1, rowCap, expectedBands,
  smallColumnsPerBand, largeRows, largeCols }`，旧入口缺省值为 24／8／2／2／2（已由下文 §10 的显式书籍入口取代）；
  `expectedBands: null` 关闭书种特定的页宽／列数检查。整数参数必须为正。
- **计划与坐标**：`planLayoutBand` 导出可重建的 `BandPlan`，段类型为 `glyph`、
  `parallel`、`gap`。该计划及 `L3Page.config/diagnostics` 不写入骨架 JSON。
- **自动留白（2026-11-17 更新）**：武英殿版每页固定显示 8 大列 × 12 大格，短页左侧、
  短列底部自动留白。已移除显式空大列指令及旧 `#` 到该指令的格式化转换；
  自动留白不生成 IR band 或 TXT 空行。预览和 OCR 导出共用 `getPageFrame`，
  少于版框列数不告警，超宽、超列仍诊断。预览版框不随内容扩张：超高向下裁切，
  超宽向左裁切（`colOffset` 可为负），分别在底部和左边缘提示；布局与源文本保留完整内容。
- **索引与标注**：`L3Band.lineIds` 明确记录成员，`indexLayout` 保存行到位置的索引；
  `projectBooks` 按 overlay 的全局 span 次序生成页内片段，跨页边界开口，单行多个
  run 分框。渲染不解析 ID 字符串、不依赖 src；ID 目前仍为序号，未实现持久身份。
- **联动**：`buildCharIndex` 同时保存每个源码码点的渲染目标，光标查询二分后直接返回，
  不再每次扫描全文寻找元素。`locateCell` 能区分同一行内被大字隔开的多个 run。
- **审计**：新鲜度、TXT、骨架独立性、旧 parser 比较和几何诊断各自报告；
  空列是信息，宽度／重叠／溢出是告警或错误，原图复核不由结构检查代替。

验收见 `test/ir-contracts.spec.ts`；最新机器证据为
[2026-11-16-gj-layout-optimized.json](../research/evidence/2026-11-16-gj-layout-optimized.json)。
完整 tokenizer、文档装配、持久锚点及 IVS 字形层仍未实现；本节不改变 §8 的历史词法兼容规则。


## 10. .gj/2 行级字号与康熙语义分离（2026-11-17）

本节替代 §8 的字头簇糖以及旧 `#+空格` 标题规则。`#` 选择大字，作用域直到物理
换行；`*` 按当前字号占一个空字格。因此 `#甲乙`、`#*甲乙`、`#**甲乙` 直接表达
大字及零／一／两格缩进，星数没有三层上限。`古文`、标点、书名括号均不重置字号。
`#甲，古文：乙丙` 必须迁移成 `#甲，`、`古文：`、`#乙丙` 三行才能保留原字号。

- **词法**：`parser/inline-tokens.ts` 统一产出字号、字、圈注、书名边界、注释及源码
  范围；IR、格式化、高亮、字体装饰共用。`parsePages/parseInline` 仅适配 IR 为
  PageModel，已删除第二套解析器和字头簇词法。
- **骨架**：移除 `IRBand.level`。缩进物化为普通大字空位，布局只消费元素字号；
  增删语义标签不改变坐标。按 profile 剔除的大字标点不占格，显式空位仍占格。
  大字也记录行内码点区间，书名框可覆盖大字格，且不反向影响字号。
- **语义**：`semantics/kangxi.ts` 解释书名／集名／部名及宿主／古文变体；Python
  对应模块为 `tools/dataset/kangxi_semantics.py`，词表共用 `kangxi-rules.json`。
  固定标题写法见 [语法文档](../../guji-preview-grid/README.md#康熙字典语义)。
  OCR 导出可派生 level 元数据，但不写回排版骨架。
- **格式化与生成**：保留换行与大字作用域，同行重复 `#` 可删除；不推断古文小字，
  不自动合并或拆分大字行。数据集草稿生成器直接输出新写法，OCR 重折只作用于小字
  区域，保护行中 `#` 至行尾及两侧换行。
- **持久化**：IR 的结构版本仍为 3，来源标记为 `sourceFormat: "gj/2"`；旧含 level
  的 JSON 必须从迁移后的 `.gj` 重建。45 页标注的 JSON/TXT 已同步；标题缩进现在
  出现在 TXT 中，因此仅空白可以与旧导出不同。标注 `.gj` 保留已有人工修订。
- **验证**：`gj2-migration.spec.ts` 使用旧解析器在迁移前捕获的独立基线，覆盖 47
  个文件（45 页标注、2 个样例）的可见字位置／字号／圈注／书名框与去空白文本。
  `kangxi-semantics.json` 对前后端运行相同用例，并比较整批迁移语料的宿主序列。
  新规则另有字号、空位、书名框、源码联动、格式化幂等和 OCR 折行保护测试。


## 10. 书籍版式与通用结构分层（2026-11-17）

当前双列古籍模型的通用结构为每大列两小列、大字横跨整个大列，定义于
`GUJI_STRUCTURE`。每页大列数、每列大格数、小/大格高度比属于书籍的具体版本，
不能作为通用引擎的缺省参数。颜色、1px 实线/虚线和开关属于显示设置；扫描
边距及纸色属于数据集图像元数据，不参与骨架占格。

书籍预设只保存三个独立参数，派生几何不能重复填写：

```ts
const bookLayout: BookLayout = {
  default: {
    id: "example-edition",
    revision: 1,
    spec: {
      schemaVersion: 1,
      bandsPerPage: 10,
      largeCellsPerBand: 15,
      smallRowsPerLargeCell: 1,
    },
  },
};
const doc = applyBookLayout(gj2ir(source), bookLayout);
const pages = layout3(doc);
```

`smallRowsPerLargeCell = n` 表示小格:大格高度为 1:n，当前接口支持正整数 n。
`compileBookLayout` 派生 `expectedBands = bandsPerPage`、
`rowCap = largeCellsPerBand * n`、`largeRows = n`、
`smallColumnsPerBand = largeCols = 2`，校验输入及乘积为正的安全整数。
康熙武英殿版为 8／12／2；同样的列数和大格数改为 n=1 后，页轨道从
16×24 变为 16×12，每大格从 2×2 小格变为 2×1 小格。

`resolvePageLayout(book, pageNo)` 选择 `book.pages[pageNo]` 或 `book.default`。
页级选择必须是完整预设，不使用容易产生残缺组合的字段级合并。
`applyBookLayout` 把默认几何写入 `meta.layout`、特殊页写入 `page.layout`，
并分别记录 `layoutPreset: { id, revision }`。没有页快照时继承文档快照。
持久化仍是 IR v3、几何仍是 v1；布局与 OCR 投影只消费数值快照，预设修订
不会自动改变已有 IR。显式重新调用 `applyBookLayout` 才会切换版式。

通用 `gj2ir` 不附带书籍默认值；`layout3` 遇到无几何配置的页面报错。
`planLayoutBand` 的文本分组不依赖几何，不再使用康熙默认参数。
历史康熙 JSON 通过 `importLegacyKangxiDocument` 按固定的武英殿版 revision 1
补齐缺失配置（不随当前数据集预设变化），已有 v1
自定义宽度（包括三小列）、`expectedBands:null` 和页级快照验证后保留。
错误版本不会回退。该兼容入口只用于已确认身份的康熙数据；新书籍必须显式声明。

数据集配置放在 manifest 同目录的 `dataset-config.json`：`layout` 保存上述书籍
预设，`scan` 保存自然像素的 `margin` 与 `background`；`scanPages[pageNo]` 可
替换某页完整扫描配置。当前康熙边距来自 0312 扫描测量：左124、上160.5、右104、
下107，自然页宽1130，纸色 #dcb68a。另一分辨率的扫描需提供对应自然像素边距。
前端 index 生成、预览、标注生成与 OCR 导出共享同一文件；旧康熙 index 仅在
source 明确为 kangxi-gold 时允许适配。OCR 增量指纹包含配置内容，版式改变会重建。
OCR 几何支持新书籍；字头语义及扫描自动检测仍有康熙专用逻辑，接入新书时需另配。

格线继续使用绝对定位的实际 Grid 轨道，z-index:-1，不影响布局；不恢复背景
平铺，避免 Safari 小数步长累计漂移。横向和纵向单位独立；有扫描时纵向单位由
版框高度/行数决定，无扫描时按大格等宽高派生小格高度。

回归覆盖两种高度比、空页和短页、同书不同页、跨页书名投影、旧自定义配置、
预设变更后的快照复现，以及预览和 OCR 的一致几何。
