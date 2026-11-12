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
import type { IRDocument, IRSegment } from "../src/ir/types";
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

describe("IR 保真性", () => {
  it("text 段保留标点；br 保留折行", () => {
    const doc = gj2ir("@9\n\n#甲於悉切，音義。\n");
    const segs = doc.pages[0].bands[0].segments;
    expect(segs.some((s) => s.kind === "text" && s.text.includes("，"))).toBe(true);
    const doc2 = gj2ir("@10\n\n前文\n後文\n");
    expect(doc2.pages[0].bands[0].segments.some((s) => s.kind === "br")).toBe(true);
  });

  it("跨行书名为单一元素，parts 指向两行", () => {
    const doc = gj2ir("@11\n\n#乙【跨行書\n\n名測試】後文\n");
    const segs = doc.pages[0].bands[0].segments;
    const book = segs.find((s) => s.kind === "book") as Extract<IRSegment, { kind: "book" }>;
    expect(book.parts).toHaveLength(2);
    expect(book.parts[0].text).toBe("跨行書");
    expect(book.parts[1]).toMatchObject({ text: "名測試", band: doc.pages[0].bands[1].id });
  });

  it("IR 页/大行结构对齐 split 的页与大行数", () => {
    const doc = gj2ir(yibu);
    const parsed = parsePages(yibu);
    expect(doc.pages.map((p) => p.no)).toEqual(parsed.map((p) => p.p));
    for (const page of doc.pages) {
      expect(page.bands.length).toBe(parsed.find((p) => p.p === page.no)!.l.length);
    }
  });

  it("src 偏移覆盖编辑器联动区间（吸收 locate.ts）", () => {
    const doc = gj2ir(yibu);
    const band = doc.pages[0].bands[0];
    const [a, b] = band.src!;
    expect(yibu.slice(a, b).trim().length).toBeGreaterThan(0);
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
