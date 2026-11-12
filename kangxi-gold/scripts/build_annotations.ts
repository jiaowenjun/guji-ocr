// 拆分 guji-preview 的 17 页人工精标样例为单页金标：
//   kangxi-gold/annotations/NNNN.gj   单页 .gj 原文（按 @N 拆分，逐行原样保留）
//   kangxi-gold/annotations/NNNN.json 结构化金标（复用 guji-preview 解析器的单页输出）
//   kangxi-gold/annotations/NNNN.txt  阅读序纯文本（CER 参考文本）
// 并做两层零漂移校验：
//   1) 单页解析结果 === 整篇解析结果中对应页（拆分不改变语义）
//   2) 整篇解析结果 === guji-preview/test/fixtures/kangxi-yibu.expected.json
//      （原 vscode-guji-preview 扩展解析器的黄金期望，见 test/parser.spec.ts）
// 运行：npx -y tsx kangxi-gold/scripts/build_annotations.ts
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parsePages } from "../../guji-preview/src/parser/parse-pages";
import type { BlockModel, LineModel, PageModel } from "../../guji-preview/src/components/guji/model";
import { gj2ir } from "../../guji-preview-grid/src/ir/gj2ir";
import { irPageToText } from "../../guji-preview-grid/src/ir/text";

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
// 模式说明：
//   默认（严格）：以 guji-preview 样例为唯一源，重新生成全部 .gj/.json/.txt，
//     并与 fixture（原扩展解析器黄金期望）逐页比对，任何不一致即失败。
//   --allow-drift：annotations/NNNN.gj 视为人工修订源（数据集对照页保存所得）——
//     已存在的 .gj 不被样例覆盖，json/txt 从该页 .gj 重新生成；
//     与样例或 fixture 不同的页列入 drift 清单（供 git diff 审查）。
const allowDrift = process.argv.includes("--allow-drift");
const fullParse = parsePages(source);
const fixture = JSON.parse(readFileSync(FIXTURE, "utf-8")) as PageModel[];
if (fullParse.length !== fixture.length && !allowDrift) {
  fail(`整篇解析页数 ${fullParse.length} ≠ fixture 页数 ${fixture.length}`);
}
if (fullParse.length !== fixture.length && allowDrift) {
  console.warn(`⚠ --allow-drift：页数 ${fullParse.length} 与 fixture ${fixture.length} 不同`);
}
const drifted: number[] = [];
fullParse.forEach((p, i) => {
  const fx = fixture[i];
  if (!fx || stable(p) !== stable(fx)) {
    if (allowDrift) {
      drifted.push(p.p);
    } else {
      fail(`整篇解析第 ${i} 页（@${p.p}）与 fixture 不一致——解析器行为漂移；人工修订请加 --allow-drift`);
    }
  }
});

mkdirSync(OUT_DIR, { recursive: true });
// 严格模式防呆：已有 .gj 与样例不同（人工修订）时拒绝执行，避免静默覆盖校对成果
if (!allowDrift) {
  const revised: number[] = [];
  chunks.forEach((chunk) => {
    const gjPath = join(OUT_DIR, `${String(chunk.page).padStart(4, "0")}.gj`);
    if (existsSync(gjPath) && readFileSync(gjPath, "utf-8") !== chunk.lines.join("\n").replace(/\n+$/, "\n")) {
      revised.push(chunk.page);
    }
  });
  if (revised.length > 0) {
    fail(
      `annotations/ 中存在人工修订页（@${revised.join(" @")}）：严格模式将覆盖它们。` +
        `确认以 annotations/*.gj 为准请加 --allow-drift；要丢弃修订恢复样例请先 git checkout kangxi-gold/annotations/`,
    );
  }
}
const summary: { page: number; chars: number }[] = [];
const manifest = JSON.parse(readFileSync(MANIFEST, "utf-8")) as {
  pages: { page: number; annotations?: Record<string, string> }[];
};
chunks.forEach((chunk, i) => {
  const sampleGj = chunk.lines.join("\n").replace(/\n+$/, "\n");
  const stem = String(chunk.page).padStart(4, "0");
  const gjPath = join(OUT_DIR, `${stem}.gj`);
  let pageGj = sampleGj;
  if (allowDrift && existsSync(gjPath)) {
    pageGj = readFileSync(gjPath, "utf-8");
    if (pageGj !== sampleGj && !drifted.includes(chunk.page)) {
      drifted.push(chunk.page);
    }
  }
  const parsed = parsePages(pageGj);
  if (parsed.length !== 1 || parsed[0].p !== chunk.page) {
    fail(`@${chunk.page} 单页解析异常：得到 ${JSON.stringify(parsed.map((p) => p.p))}`);
  }
  if (pageGj === sampleGj && stable(parsed[0]) !== stable(fullParse[i])) {
    fail(`@${chunk.page} 单页解析 ≠ 整篇解析对应页——拆分改变了语义`);
  }

  // IR（guji-ir/1）：语义结构 JSON 入库；txt 与旧口径逐字符等价（运行时断言防漂移）
  const pageIr = gj2ir(pageGj);
  if (pageIr.pages.length !== 1 || pageIr.pages[0].no !== chunk.page) {
    fail(`@${chunk.page} IR 解析异常：得到 ${JSON.stringify(pageIr.pages.map((p) => p.no))}`);
  }
  const text = irPageToText(pageIr.pages[0]);
  if (text !== pageToText(parsed[0])) {
    fail(`@${chunk.page} IR 文本流 ≠ 旧 pageToText 口径——IR 管线漂移`);
  }
  if (pageGj !== sampleGj) {
    // 保留人工修订的 .gj（不回写样例）；json/txt 从修订版重新生成
    writeFileSync(gjPath, pageGj, "utf-8");
  }
  writeFileSync(join(OUT_DIR, `${stem}.json`), JSON.stringify(pageIr, null, 2) + "\n", "utf-8");
  writeFileSync(join(OUT_DIR, `${stem}.txt`), text, "utf-8");
  summary.push({ page: chunk.page, chars: [...text.replace(/\s/g, "")].length }); // 按码点计数（扩展 B 区字 1 字）
});

// ---- 附加页：manifest 中不在样例内的页（kangxi_page_tool.py 添加的爬取草稿页）。
// 不参与样例/fixture 一致性校验（本就不是样例来源）；json/txt 从其 .gj 生成。
const samplePages = new Set(pages);
const extras = (manifest.pages ?? []).map((p) => p.page).filter((p) => !samplePages.has(p));
for (const page of extras) {
  const stem = String(page).padStart(4, "0");
  const gjPath = join(OUT_DIR, `${stem}.gj`);
  if (!existsSync(gjPath)) {
    console.warn(`⚠ 附加页 @${page} 缺 ${stem}.gj（先经数据集对照页添加），跳过`);
    continue;
  }
  const parsed = parsePages(readFileSync(gjPath, "utf-8"));
  if (parsed.length !== 1 || parsed[0].p !== page) {
    fail(`附加页 @${page} 解析异常：得到 ${JSON.stringify(parsed.map((p) => p.p))}`);
  }
  const pageIr = gj2ir(readFileSync(gjPath, "utf-8"));
  const text = irPageToText(pageIr.pages[0]);
  if (text !== pageToText(parsed[0])) {
    fail(`附加页 @${page} IR 文本流 ≠ 旧口径——IR 管线漂移`);
  }
  writeFileSync(join(OUT_DIR, `${stem}.json`), JSON.stringify(pageIr, null, 2) + "\n", "utf-8");
  writeFileSync(join(OUT_DIR, `${stem}.txt`), text, "utf-8");
  summary.push({ page, chars: [...text.replace(/\s/g, "")].length });
}
if (extras.length > 0) {
  console.log(`附加页（爬取草稿，非样例来源）：@${extras.join(" @")}`);
}
if (drifted.length > 0) {
  console.warn(
    `⚠ --allow-drift：${drifted.length} 页为人工修订（以 annotations/*.gj 为准，样例未改动）：@${drifted.join(" @")}`,
  );
}

// ---- 3. 更新 manifest 的标注记录 ----
const byPage = new Map(summary.map((s) => [s.page, s]));
for (const entry of manifest.pages ?? []) {
  if (!byPage.has(entry.page)) continue;
  const stem = String(entry.page).padStart(4, "0");
  entry.annotations = { gj: `${stem}.gj`, json: `${stem}.json`, txt: `${stem}.txt` };
}
manifest["annotations_schema"] = "guji-ir/1"; // NNNN.json 自此为 Guji IR（v1 前为 PageModel）
manifest["annotation_source"] =
  "guji-preview/src/samples/kangxi-yibu.gj（人工精标，源自 vscode-guji-preview/example；零漂移对照通过）";
writeFileSync(MANIFEST, JSON.stringify(manifest, null, 2) + "\n", "utf-8");

const total = summary.reduce((acc, s) => acc + s.chars, 0);
console.log("页  字数");
for (const s of summary) console.log(`${String(s.page).padStart(4)}  ${s.chars}`);
console.log(`共 ${summary.length} 页，正文 ${total} 字；零漂移校验全部通过，manifest 已更新`);
