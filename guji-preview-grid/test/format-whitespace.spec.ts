import { describe, expect, it } from "vitest";
import { formatDocument } from "../src/components/dataset/format-document";
import { formatSpaces } from "../src/components/dataset/format-spaces";
import { parseKangxiDocument } from "../src/datasets/kangxi";
import { buildCharIndex, charHighlightAt } from "../src/ir/linkage";
import { gj2ir } from "../src/ir/gj2ir";
import { attachLeadingCommas, formatGj } from "../src/parser/split-line";
import { formatFlow } from "../src/parser/format-flow";
import { visibleLayout } from "./helpers/visible-layout";

const view = (source: string) => visibleLayout(parseKangxiDocument(source));
const formatters = { formatFlow, formatGj, formatDocument: (s: string) => formatDocument(s).text };

describe("leading half-width spaces occupy individual cells", () => {
  it.each([
    [" 甲", "*甲"],
    ["  甲", "**甲"],
    ["  ", "**"],
    ["\t \t 甲", "**甲"],
    ["\t", ""],
    ["甲\n  乙", "甲\n**乙"],
    ["甲\n  \n乙", "甲\n**\n乙"],
    ["  【甲乙】", "**【甲乙】"],
    ["【甲\n  乙】", "【甲\n**乙】"],
    ["  #甲", "**#甲"],
    ["#甲\n  ，乙", "#甲\n**，乙"],
    ["#甲\n  \n，乙", "#甲\n**\n，乙"],
    ["  // 注释", "**// 注释"],
    ["  $ // 注\n乙", "**$ // 注\n乙"],
    ["甲  乙 \t", "甲*乙"],
  ])("preserves slots through preview and formatting: %j", (body, expected) => {
    const source = `@1\n${body}`;
    const explicit = `@1\n${expected}`;
    expect(view(source)).toEqual(view(explicit));
    for (const format of [...Object.values(formatters), (s: string) => formatSpaces(s).text]) {
      const formatted = format(source);
      expect(view(formatted)).toEqual(view(explicit));
      expect(format(formatted)).toBe(formatted);
      expect(format(source.replace(/\n/g, "\r\n"))).toBe(formatted);
    }
    for (const format of Object.values(formatters))
      expect(view(`@1\n${format(body)}`)).toEqual(view(explicit));
  });

  it("keeps page marker indentation cosmetic", () => {
    const source = " \t @1 // 页码\n  甲\n  @2\n 乙";
    const explicit = "@1 // 页码\n**甲\n@2\n*乙";
    expect(view(source)).toEqual(view(explicit));
    expect(view(formatDocument(source).text)).toEqual(view(explicit));
  });

  it("maps every leading space to its own original source position", () => {
    const source = "@1\r\n\t  𠀀";
    const line = gj2ir(source).pages[0].bands[0].lines[0];
    expect(line.elements.map(e => e.text).join("")).toBe("  𠀀");
    expect(line.cpSrcs).toEqual([5, 6, 7]);
    const index = buildCharIndex(parseKangxiDocument(source));
    expect(index.map(e => e.src)).toEqual([5, 6, 7]);
    for (const e of index) {
      const ch = String.fromCodePoint(source.codePointAt(e.src)!);
      expect(charHighlightAt(index, source, e.src + ch.length)).toEqual(e.target);
    }
  });
});

describe("formatting preserves occupied whitespace cells", () => {
  for (const [name, format] of Object.entries(formatters)) {
    it.each(["\u00a0", "\u2002", "\u2003", "\u2009", "\u202f", "\u3000", "*"])(`${name}: %j`, space => {
      for (const source of [
        `@1\n甲${space}乙`,
        `@1\n${space}甲${space}`,
        `@1\n甲${space}\n乙`,
        `@1\n甲\n${space}\n乙`,
        `@1\n【甲${space}乙】丙`,
        `@1\n#${space}// 注\n#乙`,
        `@1\n甲${space}$ // 注\n乙`,
        `@1\n甲${space}\n@2\n${space}乙`,
      ]) {
        const formatted = format(source);
        expect(view(formatted), source).toEqual(view(source));
        expect(format(formatted), source).toBe(formatted);
      }
      // A fragment has no page header to shield its leading whitespace from trim().
      const fragment = `${space}甲${space}`;
      expect(view(`@1\n${format(fragment)}`)).toEqual(view(`@1\n${fragment}`));
    });
  }

  it.each(["　", "　　", " *", " 　", "\u00a0"])("comma attachment preserves remaining slots: %j", space => {
    const source = `@1\n#甲\n，${space}\n乙`;
    const formatted = formatGj(source);
    expect(formatted).toContain("#甲，");
    expect(view(formatted)).toEqual(view(source));
    expect(formatGj(formatted)).toBe(formatted);
  });

  it.each([" ", "  ", "　", "*", "\u00a0"])("does not move commas across an occupied blank line: %j", space => {
    const source = `#甲\n${space}\n，乙`;
    expect(attachLeadingCommas(source)).toBe(source);
  });

  it.each(["  乙", "\t 乙", "  // 注", "  "])("comma attachment keeps interior whitespace semantics: %j", rest => {
    const source = `@1\n#甲\n，${rest}`;
    const formatted = formatGj(source);
    expect(view(formatted)).toEqual(view(source));
    expect(formatGj(formatted)).toBe(formatted);
  });

  it.each([
    "@1\n#甲\n\n，　\n乙",
    "@1\n甲 \t\n乙",
    "@1\n#甲　 \t\n乙丙",
    "@1\n甲　 $ // 注\n乙丙",
    "@1\n#甲¥\n\n， *\n乙",
  ])("CRLF and LF produce the same stable layout: %j", source => {
    const crlf = source.replace(/\n/g, "\r\n");
    for (const format of [formatGj, formatters.formatDocument]) {
      const formatted = format(crlf);
      expect(formatted).toBe(format(source));
      expect(view(formatted)).toEqual(view(crlf));
      expect(format(formatted)).toBe(formatted);
    }
  });
});
