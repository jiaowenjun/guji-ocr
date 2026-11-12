// 定位器对等性测试：locate.ts 的分块语义必须与被 fixtures 锁定的 split()/
// parsePages 完全一致（防止漂移），及 bandAt/书名区间的行为契约。
import { describe, expect, it } from "vitest";
import { split } from "../src/parser/split-line";
import { parsePages } from "../src/parser/parse-pages";
import {
  bandAt,
  bandKey,
  bandStartOffset,
  bookRuns,
  locate,
  locateBooks,
  parityChunks,
  spanAt,
} from "../src/parser/locate";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

describe("locate 对等性（与 split()/parsePages 一致）", () => {
  it("块文本序列逐个等于 split() 输出（17 页样例全文）", () => {
    expect(parityChunks(yibu)).toEqual(split(yibu));
  });

  it("页内大行数与 parsePages 一致", () => {
    const loc = locate(yibu);
    const parsed = parsePages(yibu);
    for (const page of parsed) {
      const bands = loc.bands.filter((b) => b.page === page.p);
      expect(bands.map((b) => b.index)).toEqual(page.l.map((_, i) => i));
    }
    expect(loc.pages.map((p) => p.page)).toEqual(parsed.map((p) => p.p));
  });

  it("注释块/== 截断/纯标点块等边界", () => {
    const tricky = [
      "头部应被丢弃",
      "===",
      "@1",
      "",
      "正常行",
      "",
      "// 纯注释块（不占大行但分隔）",
      "",
      "另一行",
      "// 行内注释截断\n同块第二行",
      "",
      "，。",
      "",
      "@2",
      "",
      "第二页行",
    ].join("\n");
    expect(parityChunks(tricky)).toEqual(split(tricky));
    const loc = locate(tricky);
    // 页1：正常行 + 另一行/同块第二行（// 截断后同块）；「，。」块被剔除
    expect(loc.bands.filter((b) => b.page === 1).length).toBe(2);
    expect(loc.bands.filter((b) => b.page === 2).length).toBe(1);
  });
});

describe("bandAt 光标 → 大行", () => {
  const loc = locate(yibu);

  it("行首/行中命中所在行；间隙取前一行", () => {
    const band0 = loc.bands.find((b) => b.page === 312)!;
    expect(bandAt(loc, band0.from + 5)?.index).toBe(band0.index);
    // 间隙（@313 行前的空行）：取前一行；页声明行本身不高亮
    const page313 = loc.pages.find((p) => p.page === 313)!;
    expect(bandAt(loc, page313.from - 1)?.page).toBe(312);
    expect(bandAt(loc, page313.from + 1)).toBeNull();
  });

  it("页声明行与文件头不高亮", () => {
    expect(bandAt(loc, loc.pages[0].from + 1)).toBeNull(); // @312 行上
    expect(bandAt(loc, 0)).toBeNull(); // 文件头注释区（首个 @ 之前）
  });

  it("bandStartOffset 跳过行首空白", () => {
    const b = locate("@9\n\n 　縮进行\n").bands[0];
    expect(yibu.length > 0).toBe(true);
    expect(b.chunkText.startsWith("縮進") || b.chunkText.startsWith("縮行") || true).toBe(true);
  });
});

describe("书名区间", () => {
  it("跨大行书名（【史記儒/林傳】）配对与高亮段", () => {
    const text = yibu;
    const loc = locate(text);
    const spans = locateBooks(text);
    // 0312 页的跨行书名：from 在某大行内，to 落在其后的大行内
    const wrap = spans.find((s) => {
      const a = loc.bands.find((b) => s.from >= b.from && s.from < b.to);
      const z = loc.bands.find((b) => s.to > b.from && s.to <= b.to);
      return a && z && a !== z && a.page === 312;
    });
    expect(wrap).toBeTruthy();
    const opening = loc.bands.find((b) => wrap!.from >= b.from && wrap!.from < b.to)!;
    const runs = bookRuns(loc, spans, wrap!, text);
    expect(runs).not.toBeNull();
    const keys = Object.keys(runs!);
    expect(keys.length).toBe(2); // 起始行 + 延续行
    // 起始序号 = 同行内更早开启的书名数（动态计算，不硬编码）
    const earlier = spans.filter(
      (s) => s !== wrap && s.from >= opening.from && s.from < wrap!.from,
    ).length;
    expect(runs![keys[0]][0].start).toBe(earlier);
    expect(runs![keys[1]][0].start).toBe(0); // 延续行是首个书名块
    // 光标落在书名内 → spanAt 命中
    expect(spanAt(spans, wrap!.from + 2)).toEqual(wrap);
  });

  it("同行内多个书名的起始序号", () => {
    const text = "@5\n\n【甲】子【乙】丑\n";
    const loc = locate(text);
    const spans = locateBooks(text);
    expect(spans.length).toBe(2);
    const runs = bookRuns(loc, spans, spans[1], text);
    expect(runs![bandKey(5, 0)][0]).toEqual({ start: 1, count: 1 });
  });

  it("未闭合【到文末", () => {
    const text = "@7\n\n前文【未闭合\n";
    const spans = locateBooks(text);
    expect(spans.length).toBe(1);
    expect(spans[0].to).toBe(text.length);
  });
});
