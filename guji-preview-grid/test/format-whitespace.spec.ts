import { describe, expect, it } from "vitest";
import { formatDocument } from "../src/components/dataset/format-document";
import { parseKangxiDocument } from "../src/datasets/kangxi";
import { attachLeadingCommas, formatGj } from "../src/parser/split-line";
import { formatFlow } from "../src/parser/format-flow";
import { visibleLayout } from "./helpers/visible-layout";

const view = (source: string) => visibleLayout(parseKangxiDocument(source));
const formatters = { formatFlow, formatGj, formatDocument: (s: string) => formatDocument(s).text };

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

  it.each(["　", "*", "\u00a0"])("does not move commas across an occupied blank line: %j", space => {
    const source = `#甲\n${space}\n，乙`;
    expect(attachLeadingCommas(source)).toBe(source);
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
