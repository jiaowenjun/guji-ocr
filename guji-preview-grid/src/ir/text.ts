// IR v3 骨架 → 阅读序纯文本（金标 NNNN.txt 的同源生成路径）。
// 大行一行 = 各小行元素文本依序拼接（行边界不产出字符）；统一 profile 清洗
// （大字为单字/合字串，不含被剔除标点，统一清洗与旧 head-raw 口径在语料上等价）。
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
  const lines = page.bands.map((band) =>
    band.lines
      .map((line) => line.elements.map((el) => cleanText(el.text)).join(""))
      .join(""),
  );
  return lines.length > 0 ? lines.join("\n") + "\n" : "";
}

export function irToText(doc: IRDocument): string {
  return doc.pages.map(irPageToText).join("");
}
