// IR 对等性测试（P1 契约）：ir2blocks ∘ gj2ir 必须逐字符等于 parsePages；
// IR 保真性（标点/折行/书名 parts）与 irToText 与旧 pageToText 的等价性。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { parsePages } from "../src/parser/parse-pages";
import { split } from "../src/parser/split-line";
import { gj2ir } from "../src/ir/gj2ir";
import { ir2blocks } from "../src/ir/ir2blocks";
import { irToText } from "../src/ir/text";
import type { IRDocument } from "../src/ir/types";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

/** 键序无关的稳定序列化（深比较） */
function stable(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(stable).join(",")}]`;
  if (v && typeof v === "object") {
    return `{${Object.entries(v as Record<string, unknown>)
      .filter(([, x]) => x !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
      .map(([k, x]) => `${JSON.stringify(k)}:${stable(x)}`)
      .join(",")}}`;
  }
  return JSON.stringify(v) ?? "null";
}

const corpus: Array<[string, string]> = [
  ["17 页样例全文", yibu],
  [
    "330 爬取草稿",
    readFileSync(
      fileURLToPath(new URL("../../kangxi-gold/annotations/0330.gj", import.meta.url)),
      "utf-8",
    ),
  ],
];

const synthetic = [
  "@1\n\n#甲【書·一篇】音義，*又【書·二篇】。\n",
  "@2\n\n#乙\n\n【跨行書\n\n名測試】後文\n",
  "@3\n\n前【未閉合\n",
  "@4\n\n#(增#丙【集韻】竝漪切。#(十五)#丁古文\n",
  "@5\n\n#　獨行#字，。\n\n#\n",
  "头部丢弃\n===\n@6\n\n正文，保留。\n",
  "@7\n\n【A\n續B】中【C】尾\n", // 延续行 + 同行两书名
  "@8\n\n#戊\n\n【開於甲\n帶內折行\n後段】終\n", // 开启行内折行（book-middle）
].map((t, i) => [`合成 ${i + 1}`, t] as [string, string]);

describe("IR 对等性：ir2blocks(gj2ir(t)) === parsePages(t)", () => {
  for (const [name, text] of [...corpus, ...synthetic]) {
    it(name, () => {
      expect(stable(ir2blocks(gj2ir(text)))).toBe(stable(parsePages(text)));
    });
  }
});

describe("IR v2 保真性与结构", () => {
  it("gloss 元素保留标点；小行=物理折行", () => {
    const doc = gj2ir("@9\n\n#甲於悉切，音義。\n");
    const els = doc.pages[0].bands[0].lines[0].elements;
    expect(els.some((e) => e.sem === "gloss" && e.text.includes("，"))).toBe(true);
    const doc2 = gj2ir("@10\n\n前文\n後文\n");
    const band = doc2.pages[0].bands[0];
    expect(band.lines).toHaveLength(2);
    expect(band.lines[0].elements[0].text).toBe("前文");
  });

  it("元素 class/sem 正交（字头大字、注文小字、带圈大字）", () => {
    const doc = gj2ir("@13\n\n#甲【書】音#(增義\n");
    const els = doc.pages[0].bands[0].lines[0].elements;
    expect(els.find((e) => e.sem === "head")).toMatchObject({ class: "large", text: "甲" });
    expect(els.find((e) => e.sem === "gloss")).toMatchObject({ class: "small" });
    expect(els.find((e) => e.sem === "mark")).toMatchObject({ class: "large", text: "增", style: "circled" });
  });

  it("跨行书名为单一 overlay，spans 指向两行且行内区间正确", () => {
    const doc = gj2ir("@11\n\n#乙【跨行書\n\n名測試】後文\n");
    const [page] = doc.pages;
    expect(page.semantics.books).toHaveLength(1);
    const book = page.semantics.books[0];
    expect(book.spans).toHaveLength(2);
    const l0 = page.bands[0].lines[0];
    const l1 = page.bands[1].lines[0];
    expect(book.spans[0]).toMatchObject({ line: l0.id, range: [1, 4] }); // 行文本“乙跨行書”
    expect(book.spans[1]).toMatchObject({ line: l1.id, range: [0, 3] });
    expect(l0.elements.find((e) => e.sem === "title")).toMatchObject({ text: "跨行書", ref: book.id });
    expect(l1.elements.find((e) => e.sem === "title")).toMatchObject({ text: "名測試", ref: book.id });
  });

  it("开启行内折行：每行各一个 title 锚", () => {
    const doc = gj2ir("@14\n\n【開於甲\n帶內折行\n後段】終\n");
    const band = doc.pages[0].bands[0];
    expect(band.lines.map((l) => l.elements.map((e) => `${e.sem}:${e.text}`)).join(" | ")).toBe(
      "title:開於甲 | title:帶內折行 | title:後段,gloss:終",
    );
  });

  it("IR 页/大行结构对齐 split 的页与大行数", () => {
    const doc = gj2ir(yibu);
    const parsed = parsePages(yibu);
    expect(doc.pages.map((p) => p.no)).toEqual(parsed.map((p) => p.p));
    for (const page of doc.pages) {
      expect(page.bands.length).toBe(parsed.find((p) => p.p === page.no)!.l.length);
    }
  });

  it("大行与小行 src 偏移指向原文", () => {
    const doc = gj2ir(yibu);
    const band = doc.pages[0].bands[3];
    expect(yibu.slice(band.src![0], band.src![1]).trim().length).toBeGreaterThan(0);
    for (const line of band.lines) {
      const raw = yibu.slice(line.src![0], line.src![1]);
      expect(raw).not.toMatch(/\n/); // 小行区间不含换行
    }
  });
});

describe("irToText 与旧 pageToText 等价", () => {
  it("17 页样例与 330 草稿逐字符相等", () => {
    // 旧口径：pageToText(parsePages(t)) —— 这里内联其逻辑作对照
    const oldText = (t: string) => {
      const pages = parsePages(t);
      const lineText = (line: unknown) =>
        ("c" in (line as object) ? (line as { c: unknown[] }).c : [line])
          .map((b) => (b as { t?: string }).t ?? "")
          .join("");
      return pages.map((p) => p.l.map(lineText).join("\n") + "\n").join("");
    };
    for (const [, text] of corpus) {
      expect(irToText(gj2ir(text))).toBe(oldText(text));
    }
  });
});

describe("IR 文档 JSON 可序列化且字段稳定", () => {
  it("round-trip 序列化不丢类型", () => {
    const doc: IRDocument = gj2ir("@12\n\n#甲【書】音義\n");
    const revived: IRDocument = JSON.parse(JSON.stringify(doc));
    expect(stable(revived)).toBe(stable(doc));
    expect(revived.meta.profile.stripPunct.length).toBeGreaterThan(0);
  });
});
