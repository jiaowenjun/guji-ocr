// 左侧 .gj 编辑器：CodeMirror 6 + Guji 语法高亮
import CodeMirror from "@uiw/react-codemirror";
import { EditorView } from "@codemirror/view";
import { syntaxHighlighting } from "@codemirror/language";
import { gujiHighlight, gujiLanguage } from "./guji-language";

export function GujiEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <CodeMirror
      value={value}
      onChange={onChange}
      extensions={[
        gujiLanguage,
        syntaxHighlighting(gujiHighlight),
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
