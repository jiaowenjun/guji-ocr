// 格式化保留字流、大字作用域和占位空格；语料检查完整几何及幂等性。
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { formatDocument } from "../src/components/dataset/format-document";
import { formatCodepoints } from "../src/components/dataset/format-codepoints";
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
  it("keeps the page 409 Zhuangzi opening mark with its title without changing the 17/16 split", () => {
    const expected = "@409\n\n今度之一寸，又減二分，應劭之說據漢尺也。\n"
      + "《莊子·庚桑楚》步仞之丘註：七尺曰仞，亦非。\n"
      + "#仟\n【廣韻】【集韻】【韻\n會】【正韻】𠀤蒼\n";
    const source = expected.replace("也。\n《莊", "也。《\n莊");
    expect(fmt(source)).toBe(expected);
    expect(fmt(expected)).toBe(expected);
    expect(visibleLayout(gj2ir(expected))).toEqual(visibleLayout(gj2ir(source)));
    const runs = layout3(gj2ir(expected))[0].bands[0].items
      .flatMap(i => i.kind === "run" ? [i.cells.length] : []);
    expect(runs).toEqual([17, 16, 5, 5]);
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
    expect(r).toEqual({ text: "@2\n\n甲*乙〇\n丙*丁·戊\n", spaces: 2, circles: 1, dots: 1, codepoints: 0 });
    expect(formatDocument(r.text)).toEqual({ text: r.text, spaces: 0, circles: 0, dots: 0, codepoints: 0 });
  });
  it("converts <U+xxxx> notation to the actual character (page 504 E708)", () => {
    const e708 = String.fromCodePoint(0xe708);
    // 3 格小字（。随末格）按均式折 2+1：本作｜E708。两列，与「甲乙丙。」同形
    expect(fmt("@504\n\n本作<U+E708>。\n")).toBe(`@504\n\n本作\n${e708}。\n`);
    expect(fmt("@504\n\n本作<U+e708>。\n")).toBe(`@504\n\n本作\n${e708}。\n`);
    // 扩展平面 5 位码位同样支持（@398 大字补录 U+2BD6E）
    expect(formatCodepoints("偏旁<U+2BD6E>形")).toEqual({ text: `偏旁${String.fromCodePoint(0x2bd6e)}形`, count: 1 });
    const r = formatDocument("@504\n\n【荀子·勸學篇】不問而告謂之傲。*本作<U+E708>。\n");
    expect(r.text).toContain(`本作${e708}。`);
    expect(r.text).not.toContain("<U+");
    expect(r.codepoints).toBe(1);
    expect(formatDocument(r.text).codepoints).toBe(0);
  });
  it("leaves invalid <U+xxxx> notation and comments untouched", () => {
    // 代理区/超平面/控制符破坏行结构或非法；3 位编号不合语法；注释区一律保留
    const src = "@1\n<U+D800><U+110000><U+001A><U+123>甲 // 注<U+E708>释\n// 整行注<U+E708>释\n";
    expect(formatCodepoints(src)).toEqual({ text: src, count: 0 });
  });
});

describe("formatDocument 全语料不变量：字符流/大字/overlay/带数不变（◎→〇、<U+xxxx>→字符 调整）", () => {
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
  // <U+xxxx>→字符 是格式化的既定转写（0504 草稿 *本作<U+E708>。）：基准同样转写后再比对
  const unescapeCp = (s: string) => formatCodepoints(s).text;

  it("语料文件非空", () => expect(files.length).toBeGreaterThan(0));

  for (const [name, src] of corpus) {
    it(`${name}`, () => {
      const a = gj2ir(unescapeCp(src));
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
