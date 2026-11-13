// IR v2 → 阅读序纯文本（金标 NNNN.txt 的同源生成路径；与旧 pageToText 等价性
// 由 build_annotations 的运行时断言与 ir.spec 锁定）。大行一行 = 各小行元素
// 文本依序拼接（行边界不产出字符，与 v1 br 语义一致）。
import type { IRDocument, IRPage } from "./types";
import { GUJI_PROFILE } from "./types";

const cleanText = (s: string) => {
  let out = s;
  for (const [from, to] of GUJI_PROFILE.normalize) out = out.split(from).join(to);
  for (const p of GUJI_PROFILE.stripPunct) out = out.split(p).join("");
  return out;
};

/** 页 → 阅读序文本 */
export function irPageToText(page: IRPage): string {
  const lines = page.bands.map((band) => {
    if (band.heading) return cleanText(band.heading.text);
    return band.lines
      .map((line) =>
        line.elements.map((el) => (el.sem === "head" ? el.text : cleanText(el.text))).join(""),
      )
      .join("");
  });
  return lines.length > 0 ? lines.join("\n") + "\n" : "";
}

export function irToText(doc: IRDocument): string {
  return doc.pages.map(irPageToText).join("");
}
