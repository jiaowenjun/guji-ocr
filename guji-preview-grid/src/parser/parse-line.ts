import { parseInline } from "./parse-inline";
export function parseLine(line: string) {
  const page = /^@(\d+)$/.exec(line);
  if (page) return { page: Number(page[1]) };
  return { c: parseInline(line) };
}
