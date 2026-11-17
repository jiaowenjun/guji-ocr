// Font fallback for all large text, independent of dictionary interpretation.
import { RangeSetBuilder } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import { scanInline } from "../../parser/inline-tokens";

const mark = Decoration.mark({ class: "cm-guji-large-char" });

function buildDecorations(view: EditorView): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  for (const { from, to } of view.visibleRanges) {
    for (let pos = from; pos < to; ) {
      const line = view.state.doc.lineAt(pos);
      for (const t of scanInline(line.text).tokens) {
        if (t.kind === "text" && t.size === "large" && t.text.trim())
          builder.add(line.from + t.from, line.from + t.to, mark);
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
