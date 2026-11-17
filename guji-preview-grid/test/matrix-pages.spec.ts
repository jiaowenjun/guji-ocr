// @vitest-environment jsdom
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MatrixPages } from "../src/components/matrix/MatrixPages";
import { gj2ir } from "../src/ir/gj2ir";
import { layout3 } from "../src/ir/layout3";
import { getPageFrame } from "../src/ir/page-frame";
import { KANGXI_LAYOUT, type IRLayoutConfig } from "../src/ir/layout-config";

function render(source: string, cells = true, config?: IRLayoutConfig) {
  const doc = gj2ir(source);
  if (config) doc.meta.layout = config;
  const root = document.createElement("div");
  root.innerHTML = renderToStaticMarkup(createElement(MatrixPages, {
    pages: layout3(doc), overlays: doc.overlays, cells,
  }));
  return root;
}

function expectFullPage(root: HTMLElement) {
  const grid = root.querySelector<HTMLElement>(".m-lines")!;
  expect(grid.style.gridTemplateColumns).toBe("repeat(16, calc(var(--guji-unit) * 1))");
  expect(grid.style.gridTemplateRows).toBe("repeat(24, calc(var(--guji-unit-v, var(--guji-unit)) * 1))");
}

describe("整页字格版框", () => {
  it.each(["@1\n", "@1\n\n\n", "@1\n\n// 空页\n"])("空页也保留 8×12 大字格：%j", (source) => {
    const root = render(source);
    expectFullPage(root);
    expect(root.querySelectorAll(".m-large, .m-cell")).toHaveLength(0);
    expect(root.querySelector(".m-layout-warning")).toBeNull();
  });

  it("短页保持字格大小，正文与书名框一起靠右，缺列留在左侧", () => {
    const root = render("@1\n\n#甲\n【乙丙】\n丁戊\n\n#己\n");
    expectFullPage(root);
    const bands = [...root.querySelectorAll<HTMLElement>(".m-band")];
    expect(root.querySelector(".m-layout-warning")).toBeNull();
    expect(bands.map((band) => band.style.gridColumn)).toEqual(["15 / span 2", "13 / span 2"]);
    expect(bands[0].querySelector<HTMLElement>(".m-large")!.style.gridRow).toBe("1 / span 2");
    const book = root.querySelector<HTMLElement>(".m-book")!;
    expect(book.style.gridColumn).toBe("16 / span 1");
    expect(book.style.gridRow).toBe("3 / span 2");
    expect(book.classList.contains("m-flush-r")).toBe(true);
    // 左侧仍有空白列时，最后一条正文列的界栏不能被当作版框左线省略。
    expect(root.querySelector(".m-band-last")).toBeNull();
  });

  it("八列都很短时仍保留全页高度，框左缘不重复画界栏", () => {
    const root = render(`@1\n\n${Array(8).fill("#甲").join("\n\n")}\n`);
    expectFullPage(root);
    const bands = root.querySelectorAll<HTMLElement>(".m-band");
    expect(bands).toHaveLength(8);
    expect(bands[7].style.gridColumn).toBe("1 / span 2");
    expect(bands[7].classList.contains("m-band-last")).toBe(true);
  });

  it("切换只改变格线显隐，不改变版框、内容或书名框位置", () => {
    const source = "@1\n\n#甲\n【乙丙】\n丁戊\n";
    const off = render(source, false);
    const on = render(source, true);
    expectFullPage(off);
    expect(on.innerHTML).toBe(off.innerHTML.replace('data-cells="off"', 'data-cells="on"'));
  });

  it("空页的实线分成 8×12 大格，每格内再用虚线划分 2×2 小格", () => {
    const root = render("@1\n");
    const vertical = [...root.querySelectorAll<HTMLElement>(".m-cell-rule-v")];
    const horizontal = [...root.querySelectorAll<HTMLElement>(".m-cell-rule-h")];
    // 版框提供外四边；每一条内部分隔都锚定对应的正文轨道。
    expect(vertical.map((line) => line.style.gridColumn)).toEqual(
      Array.from({ length: 15 }, (_, i) => `${i + 2} / ${i + 3}`),
    );
    expect(horizontal.map((line) => line.style.gridRow)).toEqual(
      Array.from({ length: 23 }, (_, i) => `${i + 2} / ${i + 3}`),
    );
    expect(vertical.filter((line) => !line.classList.contains("m-cell-rule-minor"))).toHaveLength(7);
    expect(horizontal.filter((line) => !line.classList.contains("m-cell-rule-minor"))).toHaveLength(11);
    for (const [i, line] of [...vertical.entries(), ...horizontal.entries()]) {
      expect(line.classList.contains("m-cell-rule-minor")).toBe(i % 2 === 0);
      expect(line.getAttribute("aria-hidden")).toBe("true");
    }
  });

  it("满版高度仍裁掉第 25 个小字并显示溢出标记", () => {
    const root = render(`@1\n\n${"甲".repeat(25)}\n`);
    expectFullPage(root);
    const run = root.querySelector<HTMLElement>(".m-run")!;
    expect(run.style.gridRow).toBe("1 / span 24");
    expect(run.classList.contains("m-clipped")).toBe(true);
    expect(root.querySelector<HTMLElement>(".m-over-mark")!.style.gridRow).toBe("24");
    // 单条小字居中半格时，底部提示也跟随实际字格。
    expect(root.querySelector<HTMLElement>(".m-over-mark")!.style.transform).toContain("0.5");
  });

  it("第九大列向左溢出，正文和书名框不挤进固定版框", () => {
    const source = `@1\n\n${Array(9).fill("#甲\n【乙丙】\n丁戊").join("\n\n")}\n`;
    const page = layout3(gj2ir(source))[0];
    expect(getPageFrame(page)).toEqual({ cols: 16, rows: 24, colOffset: -2 });
    const root = render(source);
    expectFullPage(root);
    expect(root.querySelector<HTMLElement>(".m-content")!.style.gridTemplateColumns)
      .toBe("repeat(18, calc(var(--guji-unit) * 1))");
    const bands = [...root.querySelectorAll<HTMLElement>(".m-band")];
    expect(bands).toHaveLength(9);
    expect(bands[0].style.gridColumn).toBe("17 / span 2");
    expect(bands[7].classList.contains("m-band-last")).toBe(true);
    expect(bands[8].style.gridColumn).toBe("1 / span 2");
    expect(root.querySelector<HTMLElement>(".m-book")!.style.gridColumn).toBe("18 / span 1");
    expect(root.querySelector(".m-over-left")!.getAttribute("aria-label")).toContain("2 个小列已隐藏");
    expect(root.querySelector(".m-over-mark")).toBeNull();
  });

  it("异常三小列导致半个大列越界时仍保留完整轨道与书名框", () => {
    const source = `@1\n\n${Array(7).fill("#甲").join("\n\n")}\n\n【乙丙】\n丁戊\n己庚\n`;
    const page = layout3(gj2ir(source))[0];
    expect(getPageFrame(page)).toEqual({ cols: 16, rows: 24, colOffset: -1 });
    const root = render(source);
    expectFullPage(root);
    expect(root.querySelector<HTMLElement>(".m-content")!.style.gridTemplateColumns)
      .toBe("repeat(17, calc(var(--guji-unit) * 1))");
    expect(root.querySelector<HTMLElement>(".m-book")!.style.gridColumn).toBe("3 / span 1");
    expect(root.querySelector(".m-over-left")!.getAttribute("aria-label")).toContain("1 个小列已隐藏");
  });

  it("左右与上下溢出同时出现，修正后提示一起消失", () => {
    const source = `@1\n\n【${"甲".repeat(25)}】\n${"乙".repeat(24)}\n\n${Array(8).fill("#丙").join("\n\n")}\n`;
    const root = render(source);
    expectFullPage(root);
    expect(root.querySelector(".m-over-left")).not.toBeNull();
    expect(root.querySelectorAll(".m-over-mark")).toHaveLength(1);
    expect(root.querySelector<HTMLElement>(".m-book")!.style.gridRow).toBe("1 / span 24");
    const fixed = render(source.replace("甲".repeat(25), "甲".repeat(24)).replace(/\n\n#丙\n$/, "\n"));
    expectFullPage(fixed);
    expect(fixed.querySelector(".m-over-left, .m-over-mark, .m-layout-warning")).toBeNull();
  });

  it("整项在下边界外时隐藏，大字跨边界时只显示剩余半格", () => {
    const root = render(`@1\n\n${"甲".repeat(23)}\n#乙丙\n`);
    expectFullPage(root);
    const glyphs = root.querySelectorAll<HTMLElement>(".m-large");
    expect(glyphs).toHaveLength(1);
    expect(glyphs[0].textContent).toBe("乙");
    expect(glyphs[0].style.gridRow).toBe("24 / span 1");
    expect(glyphs[0].classList.contains("m-clipped")).toBe(true);
    expect(root.querySelectorAll(".m-over-mark")).toHaveLength(2);
  });

  it("显式关闭固定页宽时仍按配置显示所有列", () => {
    const source = `@1\n\n${Array(9).fill("#甲").join("\n\n")}\n`;
    const root = render(source, true, { ...KANGXI_LAYOUT, expectedBands: null });
    expect(root.querySelector<HTMLElement>(".m-lines")!.style.gridTemplateColumns)
      .toBe("repeat(18, calc(var(--guji-unit) * 1))");
    expect(root.querySelector(".m-over-left, .m-layout-warning")).toBeNull();
  });
});
