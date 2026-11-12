// 左侧 .gj 编辑器：CodeMirror 6 + Guji 语法高亮
import CodeMirror from "@uiw/react-codemirror";
import { EditorView } from "@codemirror/view";
import { syntaxHighlighting } from "@codemirror/language";
import { gujiHighlight, gujiLanguage } from "./guji-language";
import { gujiLargeCharDecoration } from "./large-char-decoration";

export function GujiEditor({
  value,
  onChange,
  theme = "light",
}: {
  value: string;
  onChange: (value: string) => void;
  /** 编辑器外观（语法高亮颜色经 CSS 变量自动随 .dark 切换，此处控制编辑器底色/选区） */
  theme?: "light" | "dark";
}) {
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      theme={theme}
      extensions={[
        gujiLanguage,
        syntaxHighlighting(gujiHighlight),
        gujiLargeCharDecoration,
        EditorView.lineWrapping,
      ]}
      height="100%"
      className="h-full"
      basicSetup={{
        highlightActiveLine: true,
        foldGutter: false,
      }}
    />
  );
}
