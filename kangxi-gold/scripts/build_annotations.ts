// Explicit export only. Never rewrite .gj sources or manifest metadata.
// npx tsx kangxi-gold/scripts/build_annotations.ts [--root PATH] [--pages 312,367]
import { writeFileSync, renameSync, unlinkSync, existsSync } from "node:fs";
import { resolve, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { parseArgs } from "node:util";
import { readAnnotations } from "../../tools/dataset/annotation_source.mjs";

const { values } = parseArgs({ options: {
  root: { type: "string", default: resolve(dirname(fileURLToPath(import.meta.url)), "..") },
  pages: { type: "string" },
  "allow-drift": { type: "boolean" }, // Historical flag: .gj is now always authoritative.
} });
const pages = values.pages?.split(",").map(Number);
const { records, assertUnchanged } = readAnnotations(resolve(values.root!, "manifest.json"), pages);
const pending: { tmp: string; dest: string }[] = [];
try {
  for (const record of records) {
    const stem = String(record.page).padStart(4, "0");
    for (const [ext, content] of [["json", JSON.stringify(record.ir, null, 2) + "\n"], ["txt", record.text]]) {
      const dest = join(values.root!, "annotations", `${stem}.${ext}`);
      const tmp = `${dest}.${randomUUID()}.tmp`;
      pending.push({ tmp, dest });
      writeFileSync(tmp, content, "utf8");
    }
  }
  assertUnchanged();
  for (const { tmp, dest } of pending) renameSync(tmp, dest);
} finally {
  for (const { tmp } of pending) if (existsSync(tmp)) unlinkSync(tmp);
}
console.log(`Exported ${records.length} pages from current .gj sources. Source and manifest unchanged.`);
