import { describe, expect, it } from "vitest";
import { extractHeadwordClusters, headwordEntry, resolvePageHeadwords } from "../src/components/dataset/headwords";
import { kangxiHeading } from "../src/semantics/kangxi";

describe("Kangxi semantic entries", () => {
  it("groups main glyphs and explicit variants across lines and bands", () => {
    const source = "#(三)中，\n古文：\n#𠁧𠁩\n\n#𠕑\n【唐韻】正文";
    expect(extractHeadwordClusters(source)).toMatchObject([
      { chars: ["中", "𠁧", "𠁩", "𠕑"], head: "中", line: 0, endLine: 4 },
    ]);
    expect(extractHeadwordClusters("#下\n古\n\n文\n#丅、𠄟\n正文")[0].chars).toEqual(["下", "丅", "𠄟"]);
  });
  it("does not infer small type from 古文 in a large scope", () => {
    expect(extractHeadwordClusters("#甲古文乙丙")[0].chars).toEqual([..."甲古文乙丙"]);
    expect(extractHeadwordClusters("古文：㘳")).toEqual([]);
  });
  it("excludes circle markers, blanks, punctuation, book text and comments", () => {
    expect(extractHeadwordClusters("#(增)\n#七：// #甲")).toMatchObject([{ chars: ["七"], head: "七", line: 0 }]);
    expect(extractHeadwordClusters("#**𠀀，𠁿")).toMatchObject([{ chars: ["𠀀", "𠁿"], head: "𠁿" }]);
    expect(extractHeadwordClusters("#(十一)\n// #甲\n【書】")).toEqual([]);
  });
  it("recognizes exact title patterns with independent indentation and vocabulary checks", () => {
    for (const line of ["#康熙字典", "#*子集上", "#*丑集中", "#*亥集下", "#**一部", "#**丨部", "#　子集上"])
      expect(kangxiHeading(line), line).not.toBeNull();
    for (const line of ["#一部", "#*一部", "#***一部", "#**犬部甲", "#*甲集上", "#**狗部", "#(康)熙字典"])
      expect(kangxiHeading(line), line).toBeNull();
    expect(extractHeadwordClusters("#康熙字典\n\n#*子集上\n\n#**一部\n\n#一")).toMatchObject([{ chars: ["一"] }]);
  });
  it("a definition ends variant grouping; the next main glyph starts a new entry", () => {
    const source = "#甲\n古文：\n#乙丙\n釋義\n#丁\n釋丁";
    const entries = extractHeadwordClusters(source);
    expect(entries.map((e) => e.head)).toEqual(["甲", "丁"]);
    expect(headwordEntry(source, entries[0])).toBe("#甲\n古文：\n#乙丙\n釋義");
    expect(headwordEntry(source, entries[1])).toBe("#丁\n釋丁");
  });
});

describe("page ownership", () => {
  const texts = { 331: "@331\n\n#(三)中\n古文：\n#𠁧𠁩\n正文", 332: "@332\n\n續文" };
  it("own entries and continuation use the main host and its variant group", () => {
    expect(resolvePageHeadwords(texts[331], 331, [331, 332, 333], texts)).toMatchObject({ state: "own" });
    expect(resolvePageHeadwords("@333\n\n續文", 333, [331, 332, 333], texts)).toMatchObject({
      state: "continuation", fromPage: 331, cluster: { head: "中", chars: ["中", "𠁧", "𠁩"] },
    });
  });
  it("reports missing preceding data instead of guessing a host", () => {
    expect(resolvePageHeadwords("續文", 333, [331, 332, 333], { 331: texts[331] })).toEqual({ state: "pending", needPages: [332] });
    expect(resolvePageHeadwords(undefined, 331, [331], {})).toEqual({ state: "loading" });
    expect(resolvePageHeadwords("續文", 331, [331], {})).toEqual({ state: "none" });
  });
});
