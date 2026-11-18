import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import baseline from "./fixtures/gj2-migration-baseline.json";
import cases from "./fixtures/kangxi-semantics.json";
import { parseKangxiDocument as gj2ir } from "../src/datasets/kangxi";
import { kangxiEntries, kangxiHeading } from "../src/semantics/kangxi";
const root = fileURLToPath(new URL("../../", import.meta.url));
const sha = (s: string) => createHash("sha256").update(s).digest("hex");

// Pinned from the former explicit-fold parser before this implementation, including
// reviewed blank corrections. Book overlay order/IDs are not visual differences.
import automaticBaseline from "./fixtures/auto-flow-baseline.json";
import { visibleLayout } from "./helpers/visible-layout";
describe("automatic layout preserves reviewed pages", () => {
  for (const row of automaticBaseline) it(`@${row.page}`, () => {
    const source = readFileSync(`${root}/kangxi-gold/annotations/${String(row.page).padStart(4, "0")}.gj`, "utf8");
    expect(sha(JSON.stringify(visibleLayout(gj2ir(source))))).toBe(row.sha256);
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
