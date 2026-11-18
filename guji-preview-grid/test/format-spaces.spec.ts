// 空格格式化必须保持原文的字格、空位和装饰几何；不预先删除基准中的空位。
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { formatSpaces } from "../src/components/dataset/format-spaces";
import { parseKangxiDocument } from "../src/datasets/kangxi";
import { visibleLayout } from "./helpers/visible-layout";
import yibu from "../src/samples/kangxi-yibu.gj?raw";

const fmt = (s: string) => formatSpaces(s).text;

describe("formatSpaces 规则", () => {
  it("全角空格 1:1 → *，包括行首、行尾和纯全角空格行", () => {
    expect(fmt("字，音義。　又某也。")).toBe("字，音義。*又某也。");
    expect(fmt("甲　　乙")).toBe("甲**乙"); // 连续全角不合并（各占一格）
    expect(fmt("結尾。　")).toBe("結尾。*");
    expect(fmt("結尾。　 \t")).toBe("結尾。*"); // 只清除末尾半角空白
    expect(fmt("　又也。")).toBe("*又也。");
    expect(fmt("　　")).toBe("**");
    expect(formatSpaces("結尾。　").count).toBe(1);
    const r = formatSpaces("a　b　c");
    expect(r.count).toBe(2);
  });

  it("行内半角空格/tab 连续串 → 单个 *", () => {
    expect(fmt("深中寬厚。 又內也")).toBe("深中寬厚。*又內也");
    expect(fmt("深中寬厚。  又內也")).toBe("深中寬厚。*又內也"); // 串折叠为 1 格
    expect(fmt("甲\t乙")).toBe("甲*乙");
    expect(fmt("a b c")).toBe("a*b*c"); // 多处独立串逐个转换
    expect(formatSpaces("a  b").count).toBe(1);
  });

  it("行首半角空格不动；行尾半角空格清除", () => {
    expect(fmt(" 行首保留。又")).toBe(" 行首保留。又");
    expect(fmt("行尾清除。 ")).toBe("行尾清除。");
    expect(fmt("  ")).toBe("");
  });

  it("与已转换内容的邻接：a* b → a**b（两侧原本各占一格，等价）", () => {
    expect(fmt("字。　 又也")).toBe("字。**又也");
    expect(fmt("甲* 乙")).toBe("甲**乙");
  });

  it("large text has the same explicit blank rule as small text", () => {
    expect(fmt("#*子集上")).toBe("#*子集上");
    expect(fmt("#甲 乙")).toBe("#甲*乙");
    expect(fmt("#**一部")).toBe("#**一部");
    expect(formatSpaces("#甲 乙").count).toBe(1);
  });

  it("注释不动（整行 // 与行内 // 尾注；行尾空格仍清除）", () => {
    expect(fmt("// K0000 未编码 字")).toBe("// K0000 未编码 字");
    expect(fmt("正文句。// 附注 空格")).toBe("正文句。// 附注 空格");
    expect(fmt("// 注释尾空格　")).toBe("// 注释尾空格");
    expect(fmt("甲　// 注释尾空格　")).toBe("甲*// 注释尾空格");
    expect(fmt("　// 空位后的注释")).toBe("*// 空位后的注释");
  });

  it("保留强制换列前的全角空位，不把页码尾空白变成正文", () => {
    expect(fmt("甲　 $ // 注")).toBe("甲*$// 注");
    expect(fmt("甲　¥")).toBe("甲*¥");
    expect(fmt("@403　")).toBe("@403");
    expect(fmt("@403　// 页注　")).toBe("@403　// 页注");
  });

  it("页码行/空行不受影响；幂等", () => {
    const src = "@332\n\n民則不惑。【註】舉中氣也。　又司中。\n";
    const once = fmt(src);
    expect(once).toContain("舉中氣也。*又司中");
    expect(once.startsWith("@332\n")).toBe(true);
    expect(fmt(once)).toBe(once); // 再跑一遍无变化
    expect(formatSpaces(once).count).toBe(0);
  });

  it("书名/带圈区域内的空格同样转换（区域内 * ≡ 空格）", () => {
    expect(fmt("【周禮·春官 大宗伯】以槱燎")).toBe("【周禮·春官*大宗伯】以槱燎");
    expect(fmt("#(十一 二)")).toBe("#(十一*二)");
  });
});

describe("全语料不变量：formatSpaces 保持原文字格与装饰几何", () => {
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
      const { text } = formatSpaces(src);
      expect(visibleLayout(parseKangxiDocument(text))).toEqual(visibleLayout(parseKangxiDocument(src)));
    });
  }
});
