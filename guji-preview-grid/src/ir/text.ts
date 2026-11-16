// IR v3 骨架 → 阅读序纯文本（金标 NNNN.txt 的同源生成路径）。
// 大行一行 = 各小行元素文本依序拼接（行边界不产出字符）；统一 profile 清洗
// （大字为单字/合字串，不含被剔除标点，统一清洗与旧 head-raw 口径在语料上等价）。
import type { IRDocument, IRPage, IRProfile } from "./types";
import { compileProfile } from "./profile";

/** 页 → 阅读序文本 */
export function irPageToText(page: IRPage, profile: IRProfile): string {
  return pageToText(page, compileProfile(profile));
}

function pageToText(page: IRPage, clean: ReturnType<typeof compileProfile>): string {
  const lines = page.bands.map((band) =>
    band.lines
      .map((line) => line.elements.map((el) => clean(el.text).cells.join("")).join(""))
      .join(""),
  );
  return lines.length > 0 ? lines.join("\n") + "\n" : "";
}

export function irToText(doc: IRDocument): string {
  const clean = compileProfile(doc.meta.profile);
  return doc.pages.map((page) => pageToText(page, clean)).join("");
}
