// 编辑器装饰：# 后的单个字符（字头）用康熙字典体渲染
// 依据：中华书局宋体 02/15 平面的扩展区覆盖是子集，个别字头（如 𠆤 U+201A4）
// 会缺字出豆腐块；康熙字典体覆盖全典字头。带圈 #(、标题 # /## /### 不处理。
import { RangeSetBuilder } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";

const mark = Decoration.mark({ class: "cm-guji-large-char" });

const utf16Len = (code: number) => (code > 0xffff ? 2 : 1);

function buildDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos < to; ) {
      const line = view.state.doc.lineAt(pos);
      const text = line.text;
      for (let i = 0; i < text.length; i++) {
        if (text[i] !== "#") continue;
        const next = i + 1 < text.length ? text.codePointAt(i + 1) : undefined;
        // 行内大字 = # 后跟一个非 #、(、空白（ASCII 空格/Tab/全角空格）的字符
        if (
          next === undefined ||
          next === 0x23 || // #
          next === 0x28 || // (
          next === 0x20 ||
          next === 0x09 ||
          next === 0x3000
        ) {
          continue;
        }
        const start = line.from + i + 1;
        const len = utf16Len(next);
        builder.add(start, start + len, mark);
        i += len; // 连同代理对一起跳过（循环体另有 i++）
      }
      pos = line.to + 1;
    }
  }
  return builder.finish();
}

export const gujiLargeCharDecoration = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = buildDecorations(view);
    }
    update(update: ViewUpdate) {
      if (update.docChanged || update.viewportChanged) {
        this.decorations = buildDecorations(update.view);
      }
    }
  },
  { decorations: (plugin) => plugin.decorations },
);
