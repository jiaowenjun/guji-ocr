// IR v2 → PageModel[]（机械适配）：现有 layout/渲染零改动。
// 书名碎片重建（版面概念归适配器）：书名 overlay（src/spans）+ 行内锚 →
// parse-inline 逐行状态机的等价规则：开启行首锚 book-start（同行闭合单锚为
// book）、其后 book-middle、末锚本行闭合 book-end；延续行的非末锚为普通小字
// （parser 孤儿】语义的跨行后果）、末锚 book-end。
// 对等性契约：ir2blocks(gj2ir(t)) === parsePages(t)（test/ir.spec.ts 全语料锁定）。
import type { BlockModel, LineModel, PageModel } from "../components/flex/model";
import type { IRBand, IRBook, IRDocument, IRElement, IRLine } from "./types";
import { GUJI_PROFILE } from "./types";

const cleanText = (s: string) => {
  let out = s;
  for (const [from, to] of GUJI_PROFILE.normalize) out = out.split(from).join(to);
  for (const p of GUJI_PROFILE.stripPunct) out = out.split(p).join("");
  return out;
};

const frag = (text: string, st: string): BlockModel | null => {
  const t = cleanText(text);
  return t.length > 0 ? { t, st } : null;
};

interface Ctx {
  books: Map<string, IRBook>;
  lines: Map<string, IRLine>;
}

/** 某书名在某大行内的锚列表（按元素序） */
function anchorsInBand(band: IRBand, book: IRBook | undefined, ctx: Ctx): IRElement[] {
  if (!book) return [];
  const out: IRElement[] = [];
  for (const line of band.lines) {
    for (const el of line.elements) {
      if (el.sem === "title" && el.ref === book.id) out.push(el);
    }
  }
  void ctx;
  return out;
}

function titleBlocks(el: IRElement, band: IRBand, ctx: Ctx): BlockModel[] {
  const book = el.ref ? ctx.books.get(el.ref) : undefined;
  // 无 overlay（孤立锚）：按 v1 口径视作 [本行起, 本行止] 的开启书名
  const [s0, s1] = book?.src ?? [band.src![0], band.src![1]];
  const opener = s0 >= band.src![0] && s0 < band.src![1];
  const closesHere = s1 <= band.src![1];
  const anchors = anchorsInBand(band, book, ctx);
  const k = anchors.indexOf(el);
  const K = anchors.length;
  const last = k === K - 1;

  if (opener) {
    // 开启行：首锚 book-start（单锚同行闭合为 book）；其后 book-middle；末锚闭合 book-end
    let st: string;
    if (k === 0) st = K === 1 && closesHere ? "book" : "book-start";
    else st = last && closesHere ? "book-end" : "book-middle";
    const f = frag(el.text, st);
    return f ? [f] : [];
  }
  // 延续行：非末锚为普通小字（孤儿】跨行的 parser 语义）；末锚闭合则 book-end
  if (last && closesHere) {
    const f = frag(el.text, "book-end");
    return f ? [f] : [];
  }
  const f = frag(el.text, "");
  return f ? [f] : [];
}

function elementBlocks(el: IRElement, band: IRBand, ctx: Ctx): BlockModel[] {
  switch (el.sem) {
    case "head":
      return [{ t: el.text, si: "large" }];
    case "mark": {
      const t = cleanText(el.text);
      return t ? [{ t, si: "large", st: "circle" }] : [];
    }
    case "gloss": {
      const t = cleanText(el.text);
      return t ? [{ t }] : [];
    }
    case "title":
      return titleBlocks(el, band, ctx);
    default:
      return [];
  }
}

/** 开启书名内的「无 br」行边界：书名锚行 l0..lm 之间，l0 后的首个边界出 br
 *  （parse-inline 的 book 态换行），其后边界不出（book-half 态） */
function suppressedBoundaries(band: IRBand, ctx: Ctx): Set<number> {
  const suppress = new Set<number>();
  const anchorLinesByBook = new Map<string, number[]>();
  band.lines.forEach((line, li) => {
    for (const el of line.elements) {
      if (el.sem === "title" && el.ref) {
        const arr = anchorLinesByBook.get(el.ref) ?? [];
        arr.push(li);
        anchorLinesByBook.set(el.ref, arr);
      }
    }
  });
  for (const [ref, lines] of anchorLinesByBook) {
    const book = ctx.books.get(ref);
    if (!book?.src) continue;
    const opener = book.src[0] >= band.src![0] && book.src[0] < band.src![1];
    if (!opener || lines.length < 2) continue;
    // 边界 = 行号（br 插在第 li 行前）：首锚行后的边界出 br，其后锚行前的不出
    for (let j = 2; j < lines.length; j++) suppress.add(lines[j]);
  }
  return suppress;
}

function bandToLine(band: IRBand, ctx: Ctx): LineModel {
  if (band.heading) {
    return { t: cleanText(band.heading.text), si: "large", i: band.heading.level - 1 };
  }
  const suppress = suppressedBoundaries(band, ctx);
  const blocks: BlockModel[] = [];
  band.lines.forEach((line, li) => {
    if (li > 0 && !suppress.has(li)) blocks.push({ st: "br" }); // 行边界即折行（v1 的 br 段）
    for (const el of line.elements) blocks.push(...elementBlocks(el, band, ctx));
  });
  if (blocks.length === 0) return { st: "empty" }; // 独立 # 行等
  return { c: blocks };
}

/** IR v2 → PageModel[] */
export function ir2blocks(doc: IRDocument): PageModel[] {
  const ctx: Ctx = {
    books: new Map(doc.pages.flatMap((p) => p.semantics.books).map((b) => [b.id, b])),
    lines: new Map(
      doc.pages.flatMap((p) => p.bands.flatMap((b) => b.lines)).map((l) => [l.id, l]),
    ),
  };
  return doc.pages.map((p) => ({
    p: p.no,
    l: p.bands.map((b) => bandToLine(b, ctx)),
  }));
}
