import { describe, expect, it } from "vitest";
import { openingContinuationLines, resolvePageContinuation } from "../src/components/dataset/headwords";

describe("opening continuation lines", () => {
  it("collects leading content lines, skipping page marker, blanks and comments", () => {
    expect(openingContinuationLines("@332\n\n續文甲\n// 注釋\n\n續文乙")).toEqual([2, 5]);
  });
  it("stops at the first headword line; circle-prefix line is its start, not continuation", () => {
    expect(openingContinuationLines("續文\n#(五)\n#𠃉\n正文")).toEqual([0]);
    expect(openingContinuationLines("#中\n正文")).toEqual([]);
  });
  it("stops at a heading line even when it precedes any headword", () => {
    expect(openingContinuationLines("續文\n#**丨部\n#丨")).toEqual([0]);
    expect(openingContinuationLines("#**丨部\n#丨")).toEqual([]);
  });
  it("a fully continuing page lists all content lines", () => {
    expect(openingContinuationLines("@313\n\n釋文上\n\n釋文下")).toEqual([2, 4]);
  });
});

describe("page continuation host", () => {
  const texts = {
    331: "@331\n\n#(三)中，\n古文：\n#𠁧𠁩\n正文",
    332: "@332\n\n續文上", // 纯延续页：宿主在更早页
    333: "@333\n\n續文下\n#丁\n釋丁", // 页首延续 + 本页新字头
  };
  it("attributes leading lines to the nearest preceding host, backtracking pure-continuation pages", () => {
    expect(resolvePageContinuation(texts[333], 333, [331, 332, 333], texts)).toMatchObject({
      state: "host",
      fromPage: 331,
      cluster: { head: "中", chars: ["中", "𠁧", "𠁩"] },
      lines: [2],
    });
    expect(resolvePageContinuation(texts[332], 332, [331, 332, 333], texts)).toMatchObject({
      state: "host",
      fromPage: 331,
      lines: [2],
    });
  });
  it("reports missing preceding page text instead of guessing a host", () => {
    expect(
      resolvePageContinuation(texts[333], 333, [331, 332, 333], { 331: texts[331] }),
    ).toEqual({ state: "pending", needPages: [332] });
  });
  it("null when text not ready or no leading continuation at all", () => {
    expect(resolvePageContinuation(undefined, 331, [331], {})).toBeNull();
    expect(resolvePageContinuation("#丁\n釋丁", 331, [331], {})).toBeNull();
  });
  it("keeps leading lines but reports no host when no listed page owns them", () => {
    expect(resolvePageContinuation("續文", 331, [331], {})).toEqual({ state: "none", lines: [0] });
  });
});
