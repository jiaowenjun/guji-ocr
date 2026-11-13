// 〇格式化规则单测 + 全语料不变量。
// 与空格格式化不同：◎→〇 会改写 IR 元素文本（骨架保真存原文），逐字节不变量
// 不成立；等价口径是「渲染与文本不变」——layout3 输出（cleanChar 把 ◎〇 同归
// ○）与 irPageToText 输出逐字节不变，且骨架结构（页/行/元素/src 偏移）在
// ◎→〇 字面替换后完全一致（两者均为 1 个 BMP 码元）。
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { formatCircles } from "../src/components/dataset/format-circles";
import { gj2ir } from "../src/ir/gj2ir";
import { layout3 } from "../src/ir/layout3";
import { irToText } from "../src/ir/text";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

const fmt = (s: string) => formatCircles(s).text;

describe("formatCircles 规则", () => {
  it("◎ → 〇（1:1，含行内多处）", () => {
    expect(fmt("聲。◎按《魏志·徐邈傳》")).toBe("聲。〇按《魏志·徐邈傳》");
    expect(fmt("甲◎乙◎丙")).toBe("甲〇乙〇丙");
    expect(formatCircles("◎◎").count).toBe(2);
  });

  it("已是标准形的字符不动：〇 与 ○ 原样保留", () => {
    expect(fmt("同。〇按㐁書")).toBe("同。〇按㐁書");
    expect(fmt("切。○按字彙")).toBe("切。○按字彙");
  });

  it("标题行与注释不动", () => {
    expect(fmt("# 一部◎")).toBe("# 一部◎");
    expect(fmt("// ◎待考")).toBe("// ◎待考");
    expect(fmt("正文。// ◎按")).toBe("正文。// ◎按");
    expect(formatCircles("# 甲◎\n// ◎\n正文◎").count).toBe(1);
  });

  it("幂等", () => {
    const once = fmt("聲。◎按《魏志》");
    expect(fmt(once)).toBe(once);
    expect(formatCircles(once).count).toBe(0);
  });
});

describe("全语料不变量：◎→〇 后渲染与文本不变", () => {
  const dir = fileURLToPath(new URL("../../kangxi-gold/annotations", import.meta.url));
  const files = readdirSync(dir).filter((f) => f.endsWith(".gj"));
  const corpus: Array<[string, string]> = [
    ["样例 17 页全文", yibu],
    ...files.map((f) => [f, readFileSync(`${dir}/${f}`, "utf-8")] as [string, string]),
  ];

  it("语料文件非空", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  for (const [name, src] of corpus) {
    it(`${name}`, () => {
      const { text } = formatCircles(src);
      const a = gj2ir(src);
      const b = gj2ir(text);
      // layout3 与阅读序文本逐字节一致（◎〇 同归 ○）
      expect(JSON.stringify(layout3(b))).toBe(JSON.stringify(layout3(a)));
      expect(irToText(b)).toBe(irToText(a));
      // 骨架结构一致：原 IR pages 做同样的 ◎→〇 字面替换后应完全相等
      // （元素文本是唯一携带 ◎ 的骨架字段；src 偏移长度不变。meta.profile 的
      // normalize 声明本身含 ◎，全 JSON 替换会误伤，故只比 pages；overlays 无文本）
      expect(JSON.stringify(b.pages)).toBe(JSON.stringify(a.pages).split("◎").join("〇"));
      expect(JSON.stringify(b.overlays)).toBe(JSON.stringify(a.overlays));
    });
  }
});
