// Guji (.gj) 语法高亮：规则移植自 vscode-guji-preview/syntaxes/guji.tmLanguage.json
// token 返回 StreamLanguage 内置 token 名（comment/keyword/heading/link/strong/...），
// 由 HighlightStyle 映射到具体颜色
import { HighlightStyle, StreamLanguage } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

export const gujiLanguage = StreamLanguage.define({
  name: "guji",
  token(stream) {
    const rest = stream.string.slice(stream.pos);

    if (stream.sol()) {
      // 行注释（至行尾）
      if (/^\s*\/\//.test(rest)) {
        stream.skipToEnd();
        return "comment";
      }
      // 页码声明 ^@\d+$
      if (/^\s*@\d+\s*$/.test(rest)) {
        stream.skipToEnd();
        return "keyword";
      }
      // === 分隔条
      if (/^\s*=+$/.test(rest)) {
        stream.skipToEnd();
        return "meta";
      }
      // 一行大字（标题）^#+ text
      if (/^\s*(#+) [^#【】]+\s*$/.test(rest)) {
        stream.skipToEnd();
        return "heading";
      }
      // 跨行书名的后半段 ^text】（惰性匹配至首个 】）
      const bookEnd = rest.match(/^[^【】]+?】/);
      if (bookEnd) {
        stream.pos += bookEnd[0].length;
        return "link";
      }
    }

    // 行内注释
    if (rest.startsWith("//")) {
      stream.skipToEnd();
      return "comment";
    }
    // 标点（渲染时会被剔除，按注释弱化显示）
    const punct = rest.match(/^[，。·：:、《》]+/);
    if (punct) {
      stream.pos += punct[0].length;
      return "comment";
    }
    // 行内书名 【…】，或跨行书名的前半段（至行尾无 】）
    const book = rest.match(/^【([^【】]*)】?/);
    if (book && (book[0].endsWith("】") || book[0].length === rest.length)) {
      stream.pos += book[0].length;
      return "link";
    }
    // 带圈大字 #(A) / #(AB) / #(A
    const circle = rest.match(/^#\([^)#【】]{1,2}\)?/);
    if (circle) {
      stream.pos += circle[0].length;
      return "strong";
    }
    // 行内大字 #字
    const large = rest.match(/^#[^#【】(]/);
    if (large) {
      stream.pos += large[0].length;
      return "strong";
    }
    // 空格标记
    if (rest.startsWith("*") || rest.startsWith("　")) {
      stream.pos += 1;
      return "escape";
    }
    // 普通字符
    stream.next();
    return null;
  },
  languageData: {
    commentTokens: { line: "//" },
  },
});

export const gujiHighlight = HighlightStyle.define([
  { tag: t.comment, color: "#a1907f", fontStyle: "italic" },
  { tag: t.keyword, color: "#9a6700", fontWeight: "600" },
  { tag: t.meta, color: "#a1907f" },
  { tag: t.heading, color: "#0550ae", fontWeight: "700" },
  { tag: t.strong, color: "#0550ae", fontWeight: "600" },
  { tag: t.link, color: "#116329" },
  { tag: t.escape, color: "#8250df", fontStyle: "italic" },
]);
