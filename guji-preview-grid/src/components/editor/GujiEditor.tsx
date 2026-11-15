// 左侧 .gj 编辑器：CodeMirror 6 + Guji 语法高亮（可选 vim 双模态）
import { useEffect, useRef } from "react";
import CodeMirror from "@uiw/react-codemirror";
import { EditorView, keymap } from "@codemirror/view";
import { syntaxHighlighting } from "@codemirror/language";
import { vim } from "@replit/codemirror-vim";
import { gujiHighlight, gujiLanguage } from "./guji-language";
import { gujiKeymap } from "./keymap";
import { gujiLargeCharDecoration } from "./large-char-decoration";

const BASIC_SETUP = { highlightActiveLine: true, foldGutter: false } as const;
// 模块级常量：vim() 的返回各段（插件 spec/主题/面板）皆为包内模块级常量，
// 调用只是组装——@uiw 每渲染对 extensions 整树 reconfigure 时，CM6 按 spec
// 身份 diff 保活 ViewPlugin 实例，vim 模态/寄存器等状态不会被打回 normal。
const VIM = vim({ status: true });

export function GujiEditor({
  value,
  onChange,
  theme = "light",
  onCursor,
  requestCursor,
  onFormat,
  vimMode = false,
}: {
  value: string;
  onChange: (value: string) => void;
  /** 编辑器外观（语法高亮颜色经 CSS 变量自动随 .dark 切换，此处控制编辑器底色/选区） */
  theme?: "light" | "dark";
  /** 光标移动回调（源文本偏移，选区取 head）——供渲染列联动高亮 */
  onCursor?: (pos: number) => void;
  /** 请求把光标设到该偏移（如点击渲染行反向定位）；变化时生效一次 */
  requestCursor?: number | null;
  /** Ctrl-Alt-F 格式化（父级实现：归一 + 保存） */
  onFormat?: () => void;
  /** vim 模式（normal/insert 双模态，normal 为初始模态）；默认关 */
  vimMode?: boolean;
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
        // vim 置于其余 keymap 之前（README 建议）；emacs/Alt 键位在 normal 模态
        // 让位（见 keymap.ts），insert 模态照常生效
        ...(vimMode ? [VIM] : []),
        gujiKeymap,
        // Ctrl-Alt-F 格式化（每渲染重建闭包取最新 onFormat，与 extensions 现状一致）
        keymap.of([
          {
            key: "Ctrl-Alt-f",
            run: () => {
              onFormat?.();
              return true;
            },
          },
        ]),
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
      basicSetup={BASIC_SETUP}
    />
  );
}
