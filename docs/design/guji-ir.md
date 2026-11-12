# Guji IR（.gj ↔ 渲染的中间表示）设计

状态：已实现（P1–P3）。代码在 `guji-preview-grid/src/ir/`（`types.ts` 类型与
profile、`gj2ir.ts` 语义解析、`ir2blocks.ts` 版面适配、`text.ts` 阅读序文本、
`linkage.ts` 编辑器联动）。设计评估与决策记录见本文。

## 1. 动机

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
