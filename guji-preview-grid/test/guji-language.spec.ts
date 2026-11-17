import { describe, expect, it } from "vitest";
import { nextGujiToken } from "../src/components/editor/guji-language";
function segments(line: string, book = false) {
  const result: Array<[string, string]> = [];
  for (let pos = 0; pos < line.length;) {
    const t = nextGujiToken(line, pos, book);
    expect(t.next).toBeGreaterThan(pos);
    result.push([line.slice(pos, t.next), t.tok ?? "plain"]);
    pos = t.next; book = t.inBookAfter;
  }
  return result;
}
describe("line-scoped large highlighting", () => {
  it("keeps all content after # large, without 古文 or punctuation size inference", () => {
    expect(segments("#甲古文乙Ab𠀀")).toEqual([["#甲古文乙Ab𠀀", "strong"]]);
    expect(segments("#甲，乙")).toEqual([["#甲", "strong"], ["，", "comment"], ["乙", "strong"]]);
    expect(segments("古文：㘳").at(-1)).toEqual(["㘳", "plain"]);
    expect(segments("#(5)（z）𠂂")).toEqual([["#(5)（z）𠂂", "strong"]]);
  });
  it("marks explicit blanks independently of size and excludes comments", () => {
    expect(segments("#**甲// #注")).toEqual([["#", "strong"], ["**", "escape"], ["甲", "strong"], ["// #注", "comment"]]);
    expect(segments("#甲")[0][1]).toBe("strong");
    expect(segments("乙")[0][1]).toBe("plain");
  });
  it("Kangxi heading color comes from semantic classification", () => {
    for (const line of ["#康熙字典", "#*子集上", "#*丑集中", "#**一部"])
      expect(segments(line)).toEqual([[line, "heading"]]);
    expect(segments("#甲乙")).toEqual([["#甲乙", "strong"]]);
    expect(segments("#**一部// 注")).toEqual([["#**一部", "heading"], ["// 注", "comment"]]);
  });
  it("keeps page markers, separators and comments structural", () => {
    expect(segments("@341")).toEqual([["@341", "keyword"]]);
    expect(segments("@blank")).toEqual([..."@blank"].map((ch) => [ch, "plain"]));
    expect(segments("#")).toEqual([["#", "strong"]]);
    expect(segments("===")).toEqual([["===", "meta"]]);
    expect(segments("// #甲")).toEqual([["// #甲", "comment"]]);
  });
  it("retains cross-line book state through page markers and comments", () => {
    const first = nextGujiToken("【韻", 0);
    expect(first).toMatchObject({ tok: "link", inBookAfter: true });
    expect(nextGujiToken("@2", 0, true).inBookAfter).toBe(true);
    expect(nextGujiToken("// 註", 0, true).inBookAfter).toBe(true);
    expect(nextGujiToken("會", 0, true)).toMatchObject({ tok: "link", inBookAfter: true });
    expect(nextGujiToken("補】古文", 0, true)).toMatchObject({ next: 2, tok: "link", inBookAfter: false });
    expect(segments("史記儒】續")).toEqual([["史記儒】", "link"], ["續", "plain"]]);
  });
  it("book style does not cancel large type after the closing bracket", () => {
    expect(segments("#甲【書】乙")).toEqual([["#甲", "strong"], ["【書】", "link"], ["乙", "strong"]]);
  });
  it("advances by full codepoints from every token boundary", () => {
    const line = "#𠀀*【𠁿】甲";
    for (let pos = 0; pos < line.length;) {
      const t = nextGujiToken(line, pos);
      expect(t.next).toBeGreaterThan(pos);
      expect(/^[\uDC00-\uDFFF]/.test(line.slice(t.next))).toBe(false);
      pos = t.next;
    }
  });
});
