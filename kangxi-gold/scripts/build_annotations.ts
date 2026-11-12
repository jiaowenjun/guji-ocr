// 拆分 guji-preview 的 17 页人工精标样例为单页金标：
//   kangxi-gold/annotations/NNNN.gj   单页 .gj 原文（按 @N 拆分，逐行原样保留）
//   kangxi-gold/annotations/NNNN.json 结构化金标（复用 guji-preview 解析器的单页输出）
//   kangxi-gold/annotations/NNNN.txt  阅读序纯文本（CER 参考文本）
// 并做两层零漂移校验：
//   1) 单页解析结果 === 整篇解析结果中对应页（拆分不改变语义）
//   2) 整篇解析结果 === guji-preview/test/fixtures/kangxi-yibu.expected.json
//      （原 vscode-guji-preview 扩展解析器的黄金期望，见 test/parser.spec.ts）
// 运行：npx -y tsx kangxi-gold/scripts/build_annotations.ts
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parsePages } from "../../guji-preview/src/parser/parse-pages";
import type { BlockModel, LineModel, PageModel } from "../../guji-preview/src/components/guji/model";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "../..");
const SOURCE = join(repoRoot, "guji-preview/src/samples/kangxi-yibu.gj");
const FIXTURE = join(repoRoot, "guji-preview/test/fixtures/kangxi-yibu.expected.json");
const OUT_DIR = join(repoRoot, "kangxi-gold/annotations");
const MANIFEST = join(repoRoot, "kangxi-gold/manifest.json");

/** 键序无关的稳定序列化，用于深比较。 */
function stable(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stable).join(",")}]`;
  if (value && typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0));
    return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stable(v)}`).join(",")}}`;
  }
  return JSON.stringify(value) ?? "null";
}

/** PageModel → 阅读序文本：每个大行（band）一行，块文本顺序拼接，跳过 br/empty 结构块。 */
function pageToText(page: PageModel): string {
  const lineText = (line: LineModel): string => {
    const blocks: BlockModel[] = "c" in line ? line.c : [line];
    return blocks.map((b) => b.t ?? "").join("");
  };
  return page.l.map(lineText).join("\n") + "\n";
}

function fail(msg: string): never {
  console.error(`✗ ${msg}`);
  process.exit(1);
}

// ---- 1. 按页拆分源 .gj（首个 @N 之前的内容丢弃，如首行版本注释）----
const source = readFileSync(SOURCE, "utf-8");
const sourceLines = source.split("\n");
const chunks: { page: number; lines: string[] }[] = [];
for (const line of sourceLines) {
  const m = /^@(\d+)$/.exec(line.trim());
  if (m) {
    chunks.push({ page: Number(m[1]), lines: [line] });
  } else if (chunks.length > 0) {
    chunks[chunks.length - 1].lines.push(line);
  }
}
if (chunks.length === 0) fail("源文件中未找到 @页码 声明");
const pages = chunks.map((c) => c.page);
console.log(`拆分得到 ${pages.length} 页：@${pages[0]}–@${pages[pages.length - 1]}`);

// ---- 2. 逐页解析 + 两层零漂移校验 ----
const fullParse = parsePages(source);
const fixture = JSON.parse(readFileSync(FIXTURE, "utf-8")) as PageModel[];
if (fullParse.length !== fixture.length) {
  fail(`整篇解析页数 ${fullParse.length} ≠ fixture 页数 ${fixture.length}`);
}
fullParse.forEach((p, i) => {
  if (stable(p) !== stable(fixture[i])) {
    fail(`整篇解析第 ${i} 页（@${p.p}）与 fixture 不一致——解析器行为漂移`);
  }
});

mkdirSync(OUT_DIR, { recursive: true });
const summary: { page: number; chars: number }[] = [];
chunks.forEach((chunk, i) => {
  const pageGj = chunk.lines.join("\n").replace(/\n+$/, "\n");
  const parsed = parsePages(pageGj);
  if (parsed.length !== 1 || parsed[0].p !== chunk.page) {
    fail(`@${chunk.page} 单页解析异常：得到 ${JSON.stringify(parsed.map((p) => p.p))}`);
  }
  if (stable(parsed[0]) !== stable(fullParse[i])) {
    fail(`@${chunk.page} 单页解析 ≠ 整篇解析对应页——拆分改变了语义`);
  }

  const stem = String(chunk.page).padStart(4, "0");
  const text = pageToText(parsed[0]);
  writeFileSync(join(OUT_DIR, `${stem}.gj`), pageGj, "utf-8");
  writeFileSync(join(OUT_DIR, `${stem}.json`), JSON.stringify(parsed[0], null, 2) + "\n", "utf-8");
  writeFileSync(join(OUT_DIR, `${stem}.txt`), text, "utf-8");
  summary.push({ page: chunk.page, chars: [...text.replace(/\s/g, "")].length }); // 按码点计数（扩展 B 区字 1 字）
});

// ---- 3. 更新 manifest 的标注记录 ----
const manifest = JSON.parse(readFileSync(MANIFEST, "utf-8")) as {
  pages: { page: number; annotations?: Record<string, string> }[];
};
const byPage = new Map(summary.map((s) => [s.page, s]));
for (const entry of manifest.pages ?? []) {
  if (!byPage.has(entry.page)) continue;
  const stem = String(entry.page).padStart(4, "0");
  entry.annotations = { gj: `${stem}.gj`, json: `${stem}.json`, txt: `${stem}.txt` };
}
manifest["annotation_source"] =
  "guji-preview/src/samples/kangxi-yibu.gj（人工精标，源自 vscode-guji-preview/example；零漂移对照通过）";
writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + "\n", "utf-8");

const total = summary.reduce((acc, s) => acc + s.chars, 0);
console.log("页  字数");
for (const s of summary) console.log(`${String(s.page).padStart(4)}  ${s.chars}`);
console.log(`共 ${summary.length} 页，正文 ${total} 字；零漂移校验全部通过，manifest 已更新`);
