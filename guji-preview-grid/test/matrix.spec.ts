// 矩阵布局引擎测试：坐标推导的几何契约
// 小用例为手工推导的期望坐标；0312/一部做结构性质与字格守恒断言
import { describe, expect, it } from "vitest";
import expected0312 from "./fixtures/kangxi-0312.expected.json";
import { layoutPages } from "../src/matrix/layout";
import { parsePages } from "../src/parser/parse-pages";
import sample0312 from "../src/samples/kangxi-0312.gj?raw";
import sampleYibu from "../src/samples/kangxi-yibu.gj?raw";

const layout = (gj: string) => layoutPages(parsePages(gj));

/** 矩阵中物化的字格总数（大字 1、带圈按字符数、小字串按 cells） */
function countCells(matrix: ReturnType<typeof layoutPages>) {
  return matrix.reduce(
    (sum, pg) =>
      sum +
      pg.bands.reduce(
        (s, b) =>
          s +
          b.items.reduce((x, it) => {
            if (it.kind === "circle") return x + [...it.text].length;
            if (it.kind === "large") return x + 1;
            return x + it.cells.length;
          }, 0),
        0
      ),
    0
  );
}

/** 解析器输出中的字符总数（t 字段展平） */
function countParsedCells(pages: ReturnType<typeof parsePages>) {
  return pages.reduce(
    (sum, pg) =>
      sum +
      pg.l.reduce((s, lm) => {
        if ("c" in lm) {
          return (
            s + lm.c.reduce((x, b) => x + (b.t ? [...b.t].length : 0), 0)
          );
        }
        return s + (lm.t ? [...lm.t].length : 0);
      }, 0),
    0
  );
}

describe("layoutPages · 标题行与空行", () => {
  it("标题逐字 2×2 纵排", () => {
    const [{ bands }] = layout("@1\n\n# 甲乙");
    expect(bands).toHaveLength(1);
    expect(bands[0]).toEqual({
      cols: 2,
      rows: 4,
      items: [
        { kind: "large", r: 0, c: 0, ch: "甲" },
        { kind: "large", r: 2, c: 0, ch: "乙" },
      ],
    });
  });

  it("## 缩进一格（顶部留一个大字位）", () => {
    const [{ bands }] = layout("@1\n\n## 丙");
    expect(bands[0].items).toEqual([{ kind: "large", r: 2, c: 0, ch: "丙" }]);
    expect(bands[0].rows).toBe(4);
  });

  it("单独 # 为空白 band", () => {
    const [{ bands }] = layout("@1\n\n#\n\n# 丁");
    expect(bands[0]).toEqual({ cols: 2, rows: 2, items: [] });
    expect(bands[1].items).toEqual([{ kind: "large", r: 0, c: 0, ch: "丁" }]);
  });
});

describe("layoutPages · 复合行几何", () => {
  it("大字 + 单列小字 + 书名（k=1 时左对齐取整）", () => {
    const [{ bands }] = layout("@1\n\n#一古文#弌【唐韻】");
    expect(bands[0]).toEqual({
      cols: 2,
      rows: 8,
      items: [
        { kind: "large", r: 0, c: 0, ch: "一" },
        { kind: "run", r: 2, c: 0, cells: ["古", "文"] },
        { kind: "large", r: 4, c: 0, ch: "弌" },
        { kind: "book", r: 6, c: 0, cells: ["唐", "韻"], open: "none" },
      ],
    });
  });

  it("双行小字组右起：小行 0 在右列", () => {
    const [{ bands }] = layout("@1\n\n#一甲乙\n丙丁");
    expect(bands[0].items).toEqual([
      { kind: "large", r: 0, c: 0, ch: "一" },
      { kind: "run", r: 2, c: 1, cells: ["甲", "乙"] },
      { kind: "run", r: 2, c: 0, cells: ["丙", "丁"] },
    ]);
    expect(bands[0].rows).toBe(4);
  });

  it("带圈大字：两字合成与单字", () => {
    const [{ bands }] = layout("@1\n\n#(十五)#(增#一");
    expect(bands[0].items).toEqual([
      { kind: "circle", r: 0, c: 0, text: "十五" },
      { kind: "circle", r: 2, c: 0, text: "增" },
      { kind: "large", r: 4, c: 0, ch: "一" },
    ]);
    expect(bands[0].rows).toBe(6);
  });
});

describe("layoutPages · 书名合并（本重构的核心收益）", () => {
  it("同列连续书名合并为单一边框项", () => {
    const [{ bands }] = layout("@1\n\n#一【甲】【乙】");
    const books = bands[0].items.filter((it) => it.kind === "book");
    expect(books).toEqual([
      { kind: "book", r: 2, c: 0, cells: ["甲", "乙"], open: "none" },
    ]);
  });

  it("跨小行 wrap：首段开口向下、末段开口向上", () => {
    const [{ bands }] = layout("@1\n\n#一【丙\n丁】戊");
    expect(bands[0].items).toEqual([
      { kind: "large", r: 0, c: 0, ch: "一" },
      { kind: "book", r: 2, c: 1, cells: ["丙"], open: "bottom" },
      { kind: "book", r: 2, c: 0, cells: ["丁"], open: "top" },
      { kind: "run", r: 3, c: 0, cells: ["戊"] },
    ]);
  });

  it("跨三行书名（【字/彙/补】形态）：续行无 br，彙补并入同列（解析器既有行为）", () => {
    // 解析器在 book-half 续书名状态遇换行只产出 book-middle、不产出 br，
    // 故「彙」「补」落入同一小行列，与 flex 版渲染一致；矩阵照实复刻
    const [{ bands }] = layout("@1\n\n#一【字\n彙\n补】");
    expect(bands[0].cols).toBe(2);
    expect(bands[0].items).toEqual([
      { kind: "large", r: 0, c: 0, ch: "一" },
      { kind: "book", r: 2, c: 1, cells: ["字"], open: "bottom" },
      { kind: "book", r: 2, c: 0, cells: ["彙", "补"], open: "top" },
    ]);
    expect(bands[0].rows).toBe(4);
  });
});

describe("layoutPages · 示例文档结构", () => {
  it("0312：8 个 band（3 标题行 + 5 复合大行），标题缩进坐标正确", () => {
    const [page] = layout(sample0312);
    expect(page.p).toBe(312);
    expect(page.bands).toHaveLength(8);
    expect(page.bands[0].items.map((it) => (it as { ch: string }).ch)).toEqual([
      "康",
      "熙",
      "字",
      "典",
    ]);
    expect(page.bands[1].items.map((it) => it.r)).toEqual([2, 4, 6]); // ## 缩进一格
    expect(page.bands[2].items.map((it) => it.r)).toEqual([4, 6]); // ### 缩进两格
    expect(page.rows).toBe(
      Math.max(...page.bands.map((b) => b.rows))
    );
  });

  it("0312：跨大行书名【史記儒/林傳】拆为 bottom/top 两个开口项", () => {
    const [page] = layout(sample0312);
    const books = page.bands.flatMap((b) =>
      b.items.filter((it) => it.kind === "book")
    );
    const start = books.find(
      (it) => it.kind === "book" && it.open === "bottom"
    ) as { cells: string[] } | undefined;
    const end = books.find(
      (it) => it.kind === "book" && it.open === "top"
    ) as { cells: string[] } | undefined;
    expect(start?.cells.join("")).toBe("史記儒");
    expect(end?.cells.join("")).toBe("林傳");
  });

  it("0312：字格守恒——矩阵字格数 === 解析器字符数", () => {
    const parsed = parsePages(sample0312);
    expect(parsed).toEqual(expected0312);
    expect(countCells(layoutPages(parsed))).toBe(countParsedCells(parsed));
  });

  it("一部：17 页，字格守恒，含两字合成带圈", () => {
    const parsed = parsePages(sampleYibu);
    const matrix = layoutPages(parsed);
    expect(matrix).toHaveLength(17);
    expect(countCells(matrix)).toBe(countParsedCells(parsed));
    const circles = matrix.flatMap((pg) =>
      pg.bands.flatMap((b) => b.items.filter((it) => it.kind === "circle"))
    );
    expect(
      circles.some((it) => (it as { text: string }).text.length === 2)
    ).toBe(true); // #(十五)
    expect(matrix.every((pg) => pg.rows >= 2)).toBe(true);
  });
});
