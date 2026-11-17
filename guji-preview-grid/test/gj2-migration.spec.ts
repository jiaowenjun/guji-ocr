import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import baseline from "./fixtures/gj2-migration-baseline.json";
import cases from "./fixtures/kangxi-semantics.json";
import { gj2ir } from "../src/ir/gj2ir";
import { layout3 } from "../src/ir/layout3";
import { projectBooks } from "../src/ir/projection";
import { irToText } from "../src/ir/text";
import { kangxiEntries, kangxiHeading } from "../src/semantics/kangxi";
const root = fileURLToPath(new URL("../../", import.meta.url));
const sha = (s: string) => createHash("sha256").update(s).digest("hex");

// Expected hashes came from the OLD parser before migration, including existing user edits.
// Source IDs and line indices can change; visible cells and decoration geometry must not.
function geometry(source: string) {
  const doc = gj2ir(source), laid = layout3(doc), books = projectBooks(laid, doc.overlays);
  return laid.map((p) => ({ page: p.no, cols: p.totalCols, bands: p.bands.map((b) => ({
    cols: b.cols, rows: b.rows,
    cells: b.items.flatMap((i) => i.kind === "large" ? (i.text?.trim() ? [{
      r: i.r, c: i.c, text: i.text, size: "large", ligature: !!i.ligature,
      circle: doc.overlays.some((o) => o.kind === "circle" && o.target === i.elId),
    }] : []) : i.cells!.flatMap((ch, k) => ch.trim() ? [{ r: i.r + k, c: i.c + (i.halfShift ?? 0), text: ch, size: "small" }] : []))
      .sort((a, b) => a.r - b.r || a.c - b.c || a.size.localeCompare(b.size)),
  })), books: (books.get(p) ?? []).map((b) => ({ band: b.bandIdx, r: b.rowStart, end: b.rowEnd,
    c: b.col + (b.halfShift ?? 0), width: b.cols ?? 1, openTop: b.openTop, openBottom: b.openBottom })) }));
}

describe(".gj/2 migration preserves visible layout and content", () => {
  for (const row of baseline) it(row.file, () => {
    const source = readFileSync(`${root}/${row.file}`, "utf8");
    expect(sha(JSON.stringify(geometry(source)))).toBe(row.geometrySha256);
    expect(sha(irToText(gj2ir(source)).replace(/\s/g, ""))).toBe(row.textSha256);
  });
});

it("TypeScript and Python interpret the same Kangxi semantics", () => {
  const run = (sources: string[]) => JSON.parse(execFileSync("python3", ["-B", "-c",
    "import sys,json;sys.path.insert(0,sys.argv[1]);from kangxi_semantics import section_heading,find_host_marks;print(json.dumps([{'heading':(section_heading(s) or {}).get('level') if '\\n' not in s else None,'heads':[h for h,_ in find_host_marks(s)]} for s in json.load(sys.stdin)],ensure_ascii=False))",
    `${root}/tools/dataset`], { input: JSON.stringify(sources), encoding: "utf8" }));
  const web = (s: string) => ({ heading: s.includes("\n") ? null : kangxiHeading(s)?.level ?? null, heads: kangxiEntries(s).map((e) => e.head) });
  const expected = cases.map(({ heading, heads }) => ({ heading, heads }));
  expect(cases.map((c) => web(c.source))).toEqual(expected);
  expect(run(cases.map((c) => c.source))).toEqual(expected);
  const corpus = baseline.map((row) => readFileSync(`${root}/${row.file}`, "utf8"));
  expect(run(corpus)).toEqual(corpus.map(web));
});
