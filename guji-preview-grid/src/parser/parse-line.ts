// 移植自 vscode-guji-preview/src/parser/parse-line.ts（行为保持一致）
import { parseInline } from "./parse-inline";
import { isBlankBand } from "./structure";

export function parseLine(line: string) {
  const matchPage = line.match(/^@(\d+)$/);
  if (matchPage) {
    return { page: parseInt(matchPage[1]) };
  }

  const matchLarge = line.match(/^(#+) (.*)$/);
  if (matchLarge) {
    return {
      t: matchLarge[2],
      si: "large",
      i: matchLarge[1].length - 1,
    };
  }

  if (isBlankBand(line)) {
    return {
      st: "empty",
    };
  }

  return {
    c: parseInline(line),
  };
}
