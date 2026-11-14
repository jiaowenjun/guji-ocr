// 一键格式化 formatDocument（空格→◎→排版 串联）规则单测 + 全语料不变量。
// 顺序是本文件锁定的核心：空格先于 formatGj 折行，#丶　【唐韻】的分隔空字格
// 以 * 形态保留到折行后的行首（初校语料本有 *又… 行首形态）；若 formatGj 先跑，
// 断口 trim 会把全角空格（JS trim 认识的空白）当不占格的行首尾空白吞掉。
// 不变量口径 = formatGj 的不变量（字符流去空白/大字序列/overlay/带数不变）
// 叠加 formatCircles 的 ◎→〇 字面替换调整（◎→〇 会改元素文本）。
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { formatDocument } from "../src/components/dataset/format-document";
import { gj2ir } from "../src/ir/gj2ir";
import type { IRDocument } from "../src/ir/types";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

const fmt = (s: string) => formatDocument(s).text;

describe("formatDocument 规则（空格→◎→排版 串联）", () => {
  it("行内全角空格 → *（1:1）且不被后续折行 trim 吞掉", () => {
    expect(fmt("@1\n\n用安息。　又通作垸。\n")).toBe("@1\n\n用安息。*又通作垸。\n");
    expect(fmt("@1\n\n甲　　乙\n")).toBe("@1\n\n甲**乙\n"); // 连续全角各占一格
  });

  it("顺序锁定：#丶　【唐韻】的分隔空字格保留为折行后行首 *（不被断口 trim 吞）", () => {
    expect(fmt("@1\n\n#丶　【唐韻】知庾切。\n")).toBe("@1\n\n#丶\n*【唐韻】知庾切。\n");
  });

  it("◎ → 〇 与排版同批完成", () => {
    expect(fmt("@1\n\n聲。◎按《魏志》#丮【唐韻】几劇。\n"))
      .toBe("@1\n\n聲。〇按《魏志》\n#丮\n【唐韻】几劇。\n");
  });

  it("字头组独占一行 + 括号归一/补全 + 簇归一为标准糖形", () => {
    expect(fmt("@1\n\n#丶【唐韻】知庾切。\n")).toBe("@1\n\n#丶\n【唐韻】知庾切。\n");
    expect(fmt("@1\n\n#（z）【唐韻】音義。\n")).toBe("@1\n\n#(增)\n【唐韻】音義。\n");
  });

  it("字头断口处的半角空格同样保留为分隔 *（#(增#𠁦 音義 → *音義，非 trim 删除）", () => {
    expect(fmt("@1\n\n#(增#𠁦 音義。\n")).toBe("@1\n\n#(增)𠁦\n*音義。\n");
  });

  it("counts 汇报：空格/圈各自计数", () => {
    const r = formatDocument("@2\n\n甲　乙◎丙　丁\n");
    expect(r.text).toBe("@2\n\n甲*乙〇丙*丁\n");
    expect(r.spaces).toBe(2);
    expect(r.circles).toBe(1);
  });

  it("已是标准写法时逐字节不变；幂等", () => {
    const once = fmt("@3\n\n#丅、𠆟\n【廣韻】胡雅切。*又居虯切。\n");
    expect(formatDocument(once)).toEqual({ text: once, spaces: 0, circles: 0 });
    expect(fmt(once)).toBe(once);
  });

  it("标题行与注释不动（首尾注释行仍按 formatGj 规则删除）", () => {
    expect(fmt("@1\n\n# 一 部◎\n釋文。// ◎附註 空格\n")).toBe("@1\n\n# 一 部◎\n釋文。// ◎附註 空格\n");
    expect(fmt("// 草稿头注\n@1\n\n正文。\n// 尾注\n")).toBe("@1\n\n正文。\n");
  });
});

describe("formatDocument 全语料不变量：字符流/大字/overlay/带数不变（◎→〇 调整）", () => {
  const dir = fileURLToPath(new URL("../../kangxi-gold/annotations", import.meta.url));
  const files = readdirSync(dir).filter((f) => f.endsWith(".gj"));
  const corpus: Array<[string, string]> = [
    ["样例 17 页全文", yibu],
    ...files.map((f) => [f, readFileSync(`${dir}/${f}`, "utf-8")] as [string, string]),
  ];

  // 字符流按 profile 清洗口径比对：格式化会补全「，古文：」标点（2026-11-14
  // 标准形），标点在渲染/评测口径下本就剔除——语义字符流不变；◎〇同归○
  const charStream = (doc: IRDocument) =>
    doc.pages
      .flatMap((p) => p.bands.flatMap((b) => b.lines.flatMap((l) => l.elements.map((e) => e.text))))
      .join("")
      .replace(/\s/g, "")
      .split("")
      .map((ch) => (ch === "◎" || ch === "〇" ? "○" : ch))
      .filter((ch) => !"。，·\":：、《》".includes(ch))
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
