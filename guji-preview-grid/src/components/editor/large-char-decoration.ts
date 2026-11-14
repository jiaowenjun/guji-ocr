// 编辑器装饰：字头簇的大字字符（#X 与糖写裸字）用康熙字典体渲染
// 依据：中华书局宋体 02/15 平面的扩展区覆盖是子集，个别字头（如 𠆤 U+201A4）
// 会缺字出豆腐块；康熙字典体覆盖全典字头。带圈 #(/(、标题 # /## /### 不处理
// （圈内芯多为 BMP 常用字）；糖写裸字（#(三)丹，古文：𠁿㣋 的丹/𠁿/㣋）
// 经字头簇扫描器定位——多为 ext-B 字头，同样需要康熙字典体兜底。
import { RangeSetBuilder } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import { scanAllClusters } from "../../parser/split-line";

const mark = Decoration.mark({ class: "cm-guji-large-char" });

function buildDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos < to; ) {
      const line = view.state.doc.lineAt(pos);
      for (const cl of scanAllClusters(line.text)) {
        for (const t of cl.tokens) {
          if (t.kind === "plain") {
            // #X：原有行为（# 后一字符，含代理对）
            builder.add(line.from + t.start + 1, line.from + t.end, mark);
          } else if (t.kind === "bare") {
            builder.add(line.from + t.start, line.from + t.end, mark);
          }
        }
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
