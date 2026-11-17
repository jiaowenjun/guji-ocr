import { parseInline } from "./parse-inline";
import { isBlankBand } from "./structure";
export function parseLine(line: string) {
  const page = /^@(\d+)$/.exec(line);
  if (page) return { page: Number(page[1]) };
  if (isBlankBand(line)) return { st: "empty" };
  return { c: parseInline(line) };
}
