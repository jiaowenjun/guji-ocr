// 格式化保留物理换行与大字作用域；语料检查字符流、字号、装饰、带数与幂等性。
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { formatDocument } from "../src/components/dataset/format-document";
import { gj2ir } from "../src/ir/gj2ir";
import type { IRDocument } from "../src/ir/types";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

const fmt = (s: string) => formatDocument(s).text;

describe("formatDocument preserves type-size scopes", () => {
  it("normalizes blanks without moving them to another size scope", () => {
    expect(fmt("@1\n\n#丶　【唐韻】知庾切。\n")).toBe("@1\n\n#丶*【唐韻】知庾切。\n");
    expect(fmt("@1\n\n甲　　乙\n")).toBe("@1\n\n甲**乙\n");
  });
  it("normalizes circle shorthand and redundant size markers", () => {
    expect(fmt("@1\n\n#（z）#丹\n古文：\n#𠁿#㣋\n")).toBe("@1\n\n#(增)丹\n古文：\n#𠁿㣋\n");
  });
  it("keeps ordinary words large after # and preserves comments", () => {
    expect(fmt("@1\n\n#甲古文乙// 附注 ◎\n")).toBe("@1\n\n#甲古文乙// 附注 ◎\n");
    expect(fmt("@1\n\n#甲，\n古文：\n#乙\n")).toBe("@1\n\n#甲，\n古文：\n#乙\n");
  });
  it("reports normalization counts and is idempotent", () => {
    const r = formatDocument("@2\n\n甲　乙◎丙　丁•戊\n");
    expect(r).toEqual({ text: "@2\n\n甲*乙〇丙*丁·戊\n", spaces: 2, circles: 1, dots: 1 });
    expect(formatDocument(r.text)).toEqual({ text: r.text, spaces: 0, circles: 0, dots: 0 });
  });
});

describe("formatDocument 全语料不变量：字符流/大字/overlay/带数不变（◎→〇 调整）", () => {
  const dir = fileURLToPath(new URL("../../kangxi-gold/annotations", import.meta.url));
  const files = readdirSync(dir).filter((f) => f.endsWith(".gj"));
  const corpus: Array<[string, string]> = [
    ["样例 17 页全文", yibu],
    ...files.map((f) => [f, readFileSync(`${dir}/${f}`, "utf-8")] as [string, string]),
  ];

  // 字符流按 profile 清洗口径比对：•→· 在渲染/评测口径下剔除；◎〇同归○。
  const charStream = (doc: IRDocument) =>
    doc.pages
      .flatMap((p) => p.bands.flatMap((b) => b.lines.flatMap((l) => l.elements.map((e) => e.text))))
      .join("")
      .replace(/\s/g, "")
      .split("")
      .map((ch) => (ch === "◎" || ch === "〇" ? "○" : ch))
      .filter((ch) => !"。，·•\":：、《》".includes(ch))
      .join("");
  const largeSeq = (doc: IRDocument) =>
    JSON.stringify(
      doc.pages.flatMap((p) =>
        p.bands.flatMap((b) => b.lines.flatMap((l) => l.elements.filter((e) => e.class === "large").map((e) => e.text))),
      ),
    );
  const bandCounts = (doc: IRDocument) => JSON.stringify(doc.pages.map((p) => p.bands.length));
  const overlayKinds = (doc: IRDocument) => JSON.stringify(doc.overlays.map((o) => o.kind).sort());
  // ◎→〇 是 1 BMP 码元的等价替换（GUJI_PROFILE 同归 ○），比对前对基准做同样替换
  const circlesAdjusted = (s: string) => s.split("◎").join("〇");

  it("语料文件非空", () => expect(files.length).toBeGreaterThan(0));

  for (const [name, src] of corpus) {
    it(`${name}`, () => {
      const a = gj2ir(src);
      const b = gj2ir(fmt(src));
      expect(charStream(b)).toBe(circlesAdjusted(charStream(a)));
      expect(largeSeq(b)).toBe(circlesAdjusted(largeSeq(a)));
      expect(bandCounts(b)).toBe(bandCounts(a));
      expect(overlayKinds(b)).toBe(overlayKinds(a));
      // 幂等：格式化两遍 = 一遍
      expect(fmt(fmt(src))).toBe(fmt(src));
    });
  }
});
