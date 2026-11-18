// 格式化保留字流、大字作用域和占位空格；语料检查完整几何及幂等性。
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { formatDocument } from "../src/components/dataset/format-document";
import { parseKangxiDocument as gj2ir } from "../src/datasets/kangxi";
import type { IRDocument } from "../src/ir/types";
import { layout3 } from "../src/ir/layout3";
import { visibleLayout } from "./helpers/visible-layout";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

const fmt = (s: string) => formatDocument(s).text;

describe("formatDocument preserves type-size scopes", () => {
  it("normalizes blanks without moving them to another size scope", () => {
    expect(fmt("@1\n\n#丶　【唐韻】知庾切。\n")).toBe("@1\n\n#丶*【唐韻】知庾切。\n");
    expect(fmt("@1\n\n甲　　乙\n")).toBe("@1\n\n甲*\n*乙\n");
  });
  it.each([
    "@1\n甲\u3000\n又乙",
    "@1\n甲\n\u3000\n又乙",
    "@1\n#甲\u3000\n乙丙",
    "@1\n甲\u3000$ // 注\n乙丙",
    "@1\n甲\u3000// 注\n乙丙",
  ])("preserves explicit full-width slots across line boundaries: %s", source => {
    const formatted = fmt(source);
    expect(formatted).toContain("*");
    expect(visibleLayout(gj2ir(formatted))).toEqual(visibleLayout(gj2ir(source)));
    expect(fmt(formatted)).toBe(formatted);
  });
  it("keeps the page 403 continuation gap and the next gloss at the following column top", () => {
    // Last two big columns: the first gap is a physical line-ending U+3000;
    // the second is the restored slot before 又【韻補】.
    const source = "@403\n稱。\n【詩·召南】迨其今兮。\n【毛傳】今，急辭也。\n"
      + "【朱傳】今，今日也。不待吉也。\u3000\n又【圓覺經】無起無滅，無去來今。\n"
      + "【註】謂過去見在未來三世。*\n\n又【韻補】叶居靑切，音京。\n"
      + "【詩·周頌】有椒其馨，胡考之寧。匪且有且，\n匪今斯今。\u3000又叶居良切，音姜。\n"
      + "【易林】庭爎夜明，追古傷今。陽弱\n";
    const formatted = fmt(source);
    expect(visibleLayout(gj2ir(formatted))).toEqual(visibleLayout(gj2ir(source)));
    const runs = layout3(gj2ir(formatted))[0].bands.map(b => b.items
      .flatMap(i => i.kind === "run" ? [i.cells.join("")] : []));
    expect(runs.map(b => b.map(s => [...s].length))).toEqual([[24, 24], [24, 24]]);
    expect(runs[0][1]).toMatch(/^ 又圓覺經.*三世 $/);
    expect(runs[1][0]).toMatch(/^又韻補/);
    expect(runs[1][1]).toMatch(/^匪今斯今.*陽弱$/);
    expect(fmt(formatted)).toBe(formatted);
  });
  it("normalizes circle shorthand and redundant size markers", () => {
    expect(fmt("@1\n\n#（z）#丹\n古文：\n#𠁿#㣋\n")).toBe("@1\n\n#(增)丹\n古文：\n#𠁿㣋\n");
  });
  it("keeps ordinary words large after # and preserves comments", () => {
    expect(fmt("@1\n\n#甲古文乙// 附注 ◎\n")).toBe("@1\n\n#甲古文乙// 附注 ◎\n");
    expect(fmt("@1\n\n#甲，\n古文：\n#乙\n")).toBe("@1\n\n#甲，\n古文：\n#乙\n");
  });
  it("places a leading comma immediately after the preceding large headword", () => {
    const before = "@317\n\n#三\n，古文：\n#弎\n";
    const after = "@317\n\n#三，\n古文：\n#弎\n";
    expect(fmt(before)).toBe(after);
    expect(fmt(after)).toBe(after);
    expect(fmt("#(十)𠀀 // 字头\n，古文：\n#乙\n")).toBe("#(十)𠀀， // 字头\n古文：\n#乙\n");
  });
  it("ignores cosmetic blank lines and keeps explicit blank slots", () => {
    expect(fmt("#甲\n\n，古文：")).toBe("#甲，\n古文：\n");
    expect(fmt("正文\n，續文")).toBe("正文，\n續文\n");
    expect(fmt("#甲*\n，古文：")).toBe("#甲*\n，古文：\n");
  });
  it("does not create a band when moving a punctuation-only line", () => {
    const source = "@1\n\n#甲\n，\n古文：\n#乙\n";
    expect(fmt(source)).toBe("@1\n\n#甲，\n古文：\n#乙\n");
    expect(gj2ir(fmt(source)).pages[0].bands).toHaveLength(1);
  });
  it("reports normalization counts and is idempotent", () => {
    const r = formatDocument("@2\n\n甲　乙◎丙　丁•戊\n");
    expect(r).toEqual({ text: "@2\n\n甲*乙〇\n丙*丁·戊\n", spaces: 2, circles: 1, dots: 1 });
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
      expect(visibleLayout(b)).toEqual(visibleLayout(a));
      expect(charStream(b)).toBe(circlesAdjusted(charStream(a)));
      expect(largeSeq(b)).toBe(circlesAdjusted(largeSeq(a)));
      expect(bandCounts(b)).toBe(bandCounts(a));
      expect(overlayKinds(b)).toBe(overlayKinds(a));
      // 幂等：格式化两遍 = 一遍
      expect(fmt(fmt(src))).toBe(fmt(src));
    });
  }
});
