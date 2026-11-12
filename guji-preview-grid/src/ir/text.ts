// IR → 阅读序纯文本（金标 NNNN.txt 的同源生成路径；与旧 pageToText 等价性
// 由 build_annotations 的运行时断言与 ir.spec 锁定）。
import type { IRDocument, IRPage } from "./types";
import { GUJI_PROFILE } from "./types";

const applyProfile = (s: string) => {
  let out = s;
  for (const [from, to] of GUJI_PROFILE.normalize) out = out.split(from).join(to);
  for (const p of GUJI_PROFILE.stripPunct) out = out.split(p).join("");
  return out;
};

const cleanText = (s: string) => applyProfile(s);

/** 页 → 阅读序文本（大行一行；标题/字头/注文/书名同序拼接；br 折行不产出；
 *  跨行书名只计入属本行的 part——延续行由其自身的书名段表达，避免重复） */
export function irPageToText(page: IRPage): string {
  const lines = page.bands.map((band) => {
    if (band.heading) return cleanText(band.heading.text);
    return band.segments
      .map((seg) => {
        switch (seg.kind) {
          case "head":
            return seg.char;
          case "text":
          case "mark":
            return cleanText(seg.text);
          case "book":
            return seg.parts
              .filter((p) => !p.band || p.band === band.id)
              .map((p) => p.text.split("\n").map(cleanText).join(""))
              .join("");
          case "br":
            return "";
        }
      })
      .join("");
  });
  return lines.length > 0 ? lines.join("\n") + "\n" : "";
}

export function irToText(doc: IRDocument): string {
  return doc.pages.map(irPageToText).join("");
}
