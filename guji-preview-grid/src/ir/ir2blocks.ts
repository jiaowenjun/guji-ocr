// IR → PageModel[]（机械适配）：让现有 layout/渲染零改动过渡到 IR 管线。
// 书名碎片重建镜像 parse-inline 的逐行状态机（版面概念归适配器而非 IR）：
// - 开启行（span 起点在本行）：同行闭合单行 → book；首行 book-start + br；
//   其后 book-middle 无 br；末行本行闭合 → book-end
// - 延续行（span 起点在本行之前，孤儿】语义）：普通小字 + br，末行 book-end
// 对等性契约：ir2blocks(gj2ir(t)) === parsePages(t)（test/ir.spec.ts 全语料锁定）。
import type { BlockModel, LineModel, PageModel } from "../components/flex/model";
import type { IRBand, IRBookPart, IRDocument, IRSegment } from "./types";
import { GUJI_PROFILE } from "./types";

/** profile 清洗（不 trim/不折叠：与 parser 的块文本口径一致，保留字面 * 变来的空格） */
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

/** 开启行内的书名碎片（part 可含带内折行；closesHere = 区间在本行内闭合） */
function openerFragments(part: IRBookPart, closesHere: boolean): BlockModel[] {
  const lines = part.text.split("\n");
  const out: BlockModel[] = [];
  lines.forEach((line, i) => {
    const last = i === lines.length - 1;
    if (i === 0) {
      const f = frag(line, last && closesHere ? "book" : "book-start");
      if (f) out.push(f);
      if (!last) out.push({ st: "br" }); // book 态换行出 br（其后进入 book-half）
      return;
    }
    // 其后各行：book-middle；末行若在本行闭合则 book-end；无 br（book-half 换行）
    const f = frag(line, last && closesHere ? "book-end" : "book-middle");
    if (f) out.push(f);
  });
  return out;
}

/** 延续行内的书名碎片（孤儿】规则：普通小字 + br；末行 book-end） */
function continuationFragments(part: IRBookPart, closesHere: boolean): BlockModel[] {
  const lines = part.text.split("\n");
  const out: BlockModel[] = [];
  lines.forEach((line, i) => {
    const last = i === lines.length - 1;
    const f = frag(line, last && closesHere ? "book-end" : "");
    if (f) out.push(f);
    if (!last) out.push({ st: "br" }); // 普通态换行出 br
  });
  return out;
}

function segmentBlocks(seg: IRSegment, band: IRBand): BlockModel[] {
  switch (seg.kind) {
    case "head":
      return [{ t: seg.char, si: "large" }];
    case "mark": {
      const t = cleanText(seg.text);
      return t ? [{ t, si: "large", st: "circle" }] : [];
    }
    case "text": {
      const t = cleanText(seg.text);
      return t ? [{ t }] : [];
    }
    case "br":
      return [{ st: "br" }];
    case "book": {
      const [s0, s1] = seg.src ?? [band.src![0], band.src![1]];
      const opener = s0 >= band.src![0] && s0 < band.src![1];
      const closesHere = s1 <= band.src![1];
      const part = seg.parts[0] ?? { text: "" };
      return opener ? openerFragments(part, closesHere) : continuationFragments(part, closesHere);
    }
  }
}

function bandToLine(band: IRBand): LineModel {
  if (band.heading) {
    return { t: cleanText(band.heading.text), si: "large", i: band.heading.level - 1 };
  }
  const blocks = band.segments.flatMap((seg) => segmentBlocks(seg, band));
  if (blocks.length === 0) return { st: "empty" }; // 独立 # 行等
  return { c: blocks };
}

/** IR → PageModel[] */
export function ir2blocks(doc: IRDocument): PageModel[] {
  return doc.pages.map((p) => ({
    p: p.no,
    l: p.bands.map(bandToLine),
  }));
}
