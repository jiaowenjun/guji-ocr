import type { BookLayout } from "../../ir/layout-config";
// Normalize spacing, circles, punctuation and <U+xxxx> notation, then canonicalize without changing size boundaries.
import { formatSpaces } from "@/components/dataset/format-spaces";
import { formatCircles } from "@/components/dataset/format-circles";
import { formatDots } from "@/components/dataset/format-dots";
import { formatCodepoints } from "@/components/dataset/format-codepoints";
import { formatGj } from "@/parser/split-line";

export function formatDocument(text: string, book?: BookLayout): {
  text: string;
  spaces: number;
  circles: number;
  dots: number;
  codepoints: number;
} {
  // 转写先行：真实字符须在折行归一前进入字符流（如 0504 的 *本作<U+E708>。）。
  const codepoints = formatCodepoints(text);
  const spaces = formatSpaces(codepoints.text);
  const circles = formatCircles(spaces.text);
  const dots = formatDots(circles.text);
  return {
    text: formatGj(dots.text, book),
    spaces: spaces.count,
    circles: circles.count,
    dots: dots.count,
    codepoints: codepoints.count,
  };
}
