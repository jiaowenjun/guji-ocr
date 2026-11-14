// 左侧 .gj 编辑器：CodeMirror 6 + Guji 语法高亮
import { useEffect, useRef } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { EditorView } from "@codemirror/view";
import { syntaxHighlighting } from "@codemirror/language";
import { gujiHighlight, gujiLanguage } from "./guji-language";
import { gujiKeymap } from "./keymap";
import { gujiLargeCharDecoration } from "./large-char-decoration";

export function GujiEditor({
  value,
  onChange,
  theme = "light",
  onCursor,
  requestCursor,
}: {
  value: string;
  onChange: (value: string) => void;
  /** 编辑器外观（语法高亮颜色经 CSS 变量自动随 .dark 切换，此处控制编辑器底色/选区） */
  theme?: "light" | "dark";
  /** 光标移动回调（源文本偏移，选区取 head）——供渲染列联动高亮 */
  onCursor?: (pos: number) => void;
  /** 请求把光标设到该偏移（如点击渲染行反向定位）；变化时生效一次 */
  requestCursor?: number | null;
}) {
  const viewRef = useRef<EditorView | null>(null);

  useEffect(() => {
    const view = viewRef.current;
    // 与当前 head 相同则不动，避免回环
    if (view && requestCursor != null && view.state.selection.main.head !== requestCursor) {
      view.dispatch({
        selection: { anchor: requestCursor },
        scrollIntoView: true,
      });
      view.focus();
    }
  }, [requestCursor]);

  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      theme={theme}
      extensions={[
        gujiKeymap,
        gujiLanguage,
        syntaxHighlighting(gujiHighlight),
        gujiLargeCharDecoration,
        EditorView.lineWrapping,
      ]}
      onCreateEditor={(view) => {
        viewRef.current = view;
      }}
      onUpdate={(vu) => {
        if ((vu.selectionSet || vu.docChanged) && onCursor) {
          onCursor(vu.state.selection.main.head);
        }
      }}
      height="100%"
      className="h-full"
      basicSetup={{
        highlightActiveLine: true,
        foldGutter: false,
      }}
    />
  );
}
