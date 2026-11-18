// Construct legacy explicit skeletons for renderer/profile tests, including malformed
// three-column and overflowing snapshots that the automatic source parser cannot emit.
import { gj2ir } from "../../src/ir/gj2ir";
import { importLegacyKangxiDocument } from "../../src/datasets/kangxi";
export function foldedDocument(source: string) {
  const chunks = source.trim().split(/\n\s*\n/);
  const marked = chunks.map(c => /^@\d+$/.test(c) ? c : c + (/[$¥]\s*$/.test(c) ? "" : "$"));
  const doc = gj2ir(marked.join("\n"));
  doc.meta.lineLayout = "fold";
  return importLegacyKangxiDocument(doc);
}
