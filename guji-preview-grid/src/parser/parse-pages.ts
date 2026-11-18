import type { PageModel } from "../components/flex/model";
import { parseKangxiDocument as gj2ir } from "../datasets/kangxi";
import { bandToBlocks } from "./parse-inline";
/** Legacy view model, backed by the same grammar/profile as the matrix renderer. */
export function parsePages(text: string): PageModel[] {
  const doc = gj2ir(text);
  return doc.pages.map((p) => ({ p: p.no, l: p.bands.map((b) =>
    b.lines.every((l) => l.elements.length === 0) ? { st: "empty" } : { c: bandToBlocks(b, doc, doc.meta.profile) }) }));
}
