# Guji IR（.gj ↔ 渲染的中间表示）设计

状态：**v2 已实现**（页→大行→小行层级、大字/小字正交元素、书名 overlay）；
v1 的扁平段流已被 v2 取代，txt/评测口径与渲染行为逐字符不变。代码在
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
