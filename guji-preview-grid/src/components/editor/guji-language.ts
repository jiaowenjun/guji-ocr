// Highlighting shares the generic lexer; Kangxi heading color is semantic decoration only.
import { HighlightStyle, StreamLanguage } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";
import { scanInline, type InlineToken } from "../../parser/inline-tokens";
import { kangxiHeading } from "../../semantics/kangxi";

export type GujiTokenName = "comment" | "keyword" | "meta" | "heading" | "link" | "strong" | "escape";
const category = (t: InlineToken): GujiTokenName | null => {
  if (t.kind === "break") return "keyword";
  if (t.kind === "comment") return "comment";
  if (t.kind === "book-open" || t.kind === "book-close" || t.book) return "link";
  if (t.kind === "text" && /^[，。·•：:、《》]+$/u.test(t.text)) return "comment";
  if (t.kind === "text" && t.text === " ") return "escape";
  return t.size === "large" ? "strong" : null;
};
export function nextGujiToken(line: string, pos: number, inBook = false): {
  next: number; tok: GujiTokenName | null; inBookAfter: boolean;
} {
  if (pos === 0) {
    if (/^\s*@\d+\s*$/.test(line))
      return { next: line.length, tok: "keyword", inBookAfter: inBook };
    if (/^\s*=+\s*$/.test(line)) return { next: line.length, tok: "meta", inBookAfter: inBook };
    if (/^\t*\/\//.test(line)) return { next: line.length, tok: "comment", inBookAfter: inBook };
    if (kangxiHeading(line)) return { next: line.indexOf("//") < 0 ? line.length : line.indexOf("//"), tok: "heading", inBookAfter: false };
  }
  const tokens = scanInline(line, inBook).tokens;
  const at = tokens.findIndex((t) => pos >= t.from && pos < t.to);
  if (at < 0) return { next: Math.min(pos + 1, line.length), tok: null, inBookAfter: inBook };
  const tok = category(tokens[at]);
  let next = tokens[at].to;
  // Merge syntax runs; keep plain content at codepoint granularity for cursor replay.
  if (tok !== null) for (let i = at + 1; i < tokens.length && category(tokens[i]) === tok; i++) next = tokens[i].to;
  return { next, tok, inBookAfter: scanInline(line.slice(0, next), inBook).inBookAfter };
}

/** StreamLanguage 解析态：inBook = 上一行行尾的书名跨行态（copyState 浅拷贝快照，
 *  空行走 blankLine 旁路原样穿透）；lineBook = 本行运行态（sol 注入、逐 token 更新） */
interface GujiStreamState {
  inBook: boolean;
  lineBook: boolean;
}

export const gujiLanguage = StreamLanguage.define({
  name: "guji",
  startState: (): GujiStreamState => ({ inBook: false, lineBook: false }),
  token(stream, state: GujiStreamState) {
    if (stream.sol()) state.lineBook = state.inBook;
    const { next, tok, inBookAfter } = nextGujiToken(stream.string, stream.pos, state.lineBook);
    if (next <= stream.pos) stream.next(); // 防御：绝不原地踏步
    else stream.pos = next;
    state.lineBook = inBookAfter;
    if (stream.eol()) state.inBook = inBookAfter;
    return tok;
  },
  languageData: {
    commentTokens: { line: "//" },
  },
});

// 颜色经 CSS 变量引用（index.css 亮/暗两套 --guji-hl-*），随主题切换
export const gujiHighlight = HighlightStyle.define([
  { tag: t.comment, color: "var(--guji-hl-comment)", fontStyle: "italic" },
  { tag: t.keyword, color: "var(--guji-hl-keyword)", fontWeight: "600" },
  { tag: t.meta, color: "var(--guji-hl-comment)" },
  { tag: t.heading, color: "var(--guji-hl-heading)", fontWeight: "700" },
  { tag: t.strong, color: "var(--guji-hl-heading)", fontWeight: "600" },
  { tag: t.link, color: "var(--guji-hl-link)" },
  { tag: t.escape, color: "var(--guji-hl-escape)", fontStyle: "italic" },
]);
