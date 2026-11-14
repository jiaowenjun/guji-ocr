// .gj 一键格式化（编辑器工具栏「格式化」按钮）：合并原「空格格式化」「〇格式化」
// 两个按钮，按 空格 → ◎ → • → 排版 的顺序串联四个纯函数：
//   1. formatSpaces：行内空格 → 显式 *（全角 1:1、半角串合并；标题行/注释不动）
//   2. formatCircles：按语标记 ◎ → 〇（语料标准写法；标题行/注释不动）
//   3. formatDots：书名间隔号 • → ·（站点文本非标准写法；标题行/注释不动）
//   4. formatGj：括号/速记归一、#(X 补右括号、字头组独占一行、首尾空行/注释删除
//
// 顺序依据（空格必须先于 formatGj）：字头断口两侧的 trim 只应清掉不占格的行首尾
// 半角空格——全角空格　是 JS trim 认识的空白，若 formatGj 先跑，#丶　【唐韻】的
// 分隔空字格会被断口 trim 吞掉；先转成 * 则作为内容保留到折行后的行首（初校语料
// 本就有 *又… 的行首形态）。◎/• 与空格/折行无交互，位置不限。
import { formatSpaces } from "@/components/dataset/format-spaces";
import { formatCircles } from "@/components/dataset/format-circles";
import { formatDots } from "@/components/dataset/format-dots";
import { formatGj } from "@/parser/split-line";

export function formatDocument(text: string): {
  text: string;
  spaces: number;
  circles: number;
  dots: number;
} {
  const spaces = formatSpaces(text);
  const circles = formatCircles(spaces.text);
  const dots = formatDots(circles.text);
  return { text: formatGj(dots.text), spaces: spaces.count, circles: circles.count, dots: dots.count };
}
