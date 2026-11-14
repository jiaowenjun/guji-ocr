// 移植自 vscode-guji-preview/src/parser/parse-inline.ts
// 修改点：原版 state 为模块级变量，改为 parseInline 函数局部变量，避免跨调用泄漏；
// 并删除原版遗留的 console.log 调试语句。解析行为保持一致。
// 【2026-11-14】镜像 gj2ir 的字头簇糖（带圈续写 (Y)、裸字大写、古文标记）——
// build_annotations 的旧解析器 TXT 等价断言对糖文件保持绿。糖状态行内局部：
// 输入经 split() 已剥标点，标记形退化为裸「古文」（，？古文：? 的可选标点天然失配）
import type { BlockModel } from "../components/flex/model";
import { isBareLargeChar } from "./split-line";

type State =
  | "normal"
  | "book"
  | "book-half"
  | "large"
  | "large-circle"
  | "large-circle-stack";
export type BookStyle = "book" | "book-start" | "book-middle" | "book-end";

export function isChar(c: string) {
  return !c.match(/[#【】\n]/);
}

export function parseInline(line: string) {
  let blocks: BlockModel[] = [];
  let frag = "";
  let state: State = "normal";

  // 字头簇糖状态（与 gj2ir 词法镜像）
  let lastLarge: "circled" | "plain" | "bare" | null = null;
  let variantMode = false;
  let skipUntil = -1;

  const consumeFrag = function () {
    if (frag.length > 0) {
      blocks.push({
        t: frag,
      });
      frag = "";
    }
  };

  const consumeBookFrag = function (style: BookStyle) {
    if (frag.length > 0) {
      blocks.push({
        t: frag,
        st: style,
      });
      frag = "";
    }
  };

  [...line].forEach((raw, i) => {
    if (i < skipUntil) return;
    // * 转为空格
    const c = raw === "*" ? " " : raw;

    switch (state) {
      // large状态
      case "large":
        if (c === "(") {
          state = "large-circle";
          break;
        }
        if (isChar(c)) {
          blocks.push({
            t: c,
            si: "large",
          });
          lastLarge = "plain";
        }
        // 消耗一个字符后恢复到 normal
        state = "normal";
        break;

      case "large-circle":
        // 闭合判定前瞻 i+1（单字符内芯 #(增)，与 IR 词法一致——原先漏看产生杂散 )）
        if (line.at(i + 1) === ")" || line.at(i + 2) === ")" || line.at(i + 3) === ")") {
          state = "large-circle-stack";
          if (isChar(c)) {
            frag += c;
          }
          break;
        } else if (isChar(c)) {
          blocks.push({
            t: c,
            si: "large",
            st: "circle",
          });
          lastLarge = "circled";
          // 消耗一个字符后恢复到 normal
          state = "normal";
        }
        break;

      case "large-circle-stack":
        if (c === ")") {
          blocks.push({
            t: frag,
            si: "large",
            st: "circle",
          });
          lastLarge = "circled";
          frag = "";
          state = "normal";
        } else if (isChar(c)) {
          frag += c;
        }
        break;

      // normal状态
      case "normal":
        // 进入 large 状态
        if (c === "#") {
          // 保存小字片段
          consumeFrag();
          state = "large";
          lastLarge = null;
        }
        // 进入 book 状态
        else if (c === "【") {
          // 保存小字片段
          consumeFrag();
          state = "book";
          lastLarge = null;
          variantMode = false;
        }
        // 换行
        else if (c === "\n") {
          // 保存小字片段
          consumeFrag();
          // 加换行标记
          blocks.push({ st: "br" });
          lastLarge = null;
          variantMode = false;
        }
        // book 后半部结束
        else if (c === "】") {
          // 保存小字片段
          consumeBookFrag("book-end");
          lastLarge = null;
          variantMode = false;
        }
        // 糖：带圈续写——( 紧随大字 token 即 #( 的省 # 形
        else if ((c === "(" || c === "（") && lastLarge) {
          consumeFrag(); // 挂起小字先入列（与 # 分支同序，保阅读序）
          state = "large-circle";
        }
        // 糖：古文异体标记（大字 token 后紧邻；行首承接——此处输入已剥标点，
        // 行首形无冒号可依，仅认大字后的裸「古文」，承接形由 # 变体显式表达）
        else if (
          lastLarge &&
          c === "古" &&
          /^，?古文[:：]?/.test(line.slice(i))
        ) {
          const mm = /^，?古文[:：]?/.exec(line.slice(i))!;
          frag += mm[0];
          variantMode = true;
          lastLarge = null;
          skipUntil = i + mm[0].length;
        }
        // 糖：裸字大写——任意大字 token 后（字头连写串）或标记/、 后（变体，
        // 连串）。「古」排除：「古文」标记首字/跨行半个标记，不参与裸写
        else if (isBareLargeChar(c) && (variantMode || (lastLarge !== null && c !== "古"))) {
          consumeFrag(); // 挂起小字先入列（保阅读序）
          blocks.push({ t: c, si: "large" });
          lastLarge = "bare";
        }
        // 普通字符，添加到小字片段
        else if (isChar(c)) {
          frag += c;
          // 、 紧随大字/变体链 → 并列变体语境（裸字连写继续）；其余小字退出
          if (c === "、" && (lastLarge || variantMode)) variantMode = true;
          else variantMode = false;
          lastLarge = null;
        }
        break;

      // book 状态
      case "book":
        // 书名结束
        if (c === "】") {
          // 保存书名
          consumeBookFrag("book");
          // 恢复到 normal 状态
          state = "normal";
        }
        // 换行
        else if (c === "\n") {
          // 保存前半书名
          consumeBookFrag("book-start");
          // 加换行标记
          blocks.push({ st: "br" });
          // 进入 book-start 状态
          state = "book-half";
        }
        // 普通字符，添加到书名片段
        else if (isChar(c)) {
          frag += c;
        } else {
          state = "normal";
        }
        break;
      // 后半书名
      case "book-half":
        // 书名结束
        if (c === "】") {
          // 保存书名
          consumeBookFrag("book-end");
          // 恢复到 normal 状态
          state = "normal";
        }
        // 普通字符，添加到书名片段
        else if (isChar(c)) {
          frag += c;
        }
        // 换行，保存中段书名
        else if (c === "\n") {
          consumeBookFrag("book-middle");
        } else {
          state = "normal";
        }
        break;
    }
  });

  if (state === "normal") {
    consumeFrag();
  } else if (state === "book") {
    consumeBookFrag("book-start");
    state = "book-half";
  } else if (state === "book-half") {
    consumeBookFrag("book-middle");
  }
  return blocks;
}
