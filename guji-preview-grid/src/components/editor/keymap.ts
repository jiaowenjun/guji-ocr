// 编辑器快捷键：
// Ctrl-J 下一行并入本行末尾——先去本行行尾空格与下一行行首空格（含全角），
//   删除中间换行完成拼接，光标落在接缝处；
// Ctrl-O 在本行上方插入空行，光标移到空行行首。
// Ctrl-K 删光标到行尾；已在行尾时删换行（emacs kill-line，同 CM deleteToLineEnd）。
// Ctrl-U 删光标到行首；已在行首时删前一换行（对称语义，同 CM deleteToLineStart）。
//   有选区时两者均只删选区（CM deleteBy 语义）。
// Alt/Option-Z 插入 #(增)，Alt/Option-数字插入 #(数字)（如 Alt-1 → #(1)）。
// \s 含 U+3000 全角空格，无需另列。
import { Prec } from "@codemirror/state";
import { EditorView, keymap, type Command } from "@codemirror/view";

const joinNextLine: Command = (view) => {
  const { state } = view;
  const line = state.doc.lineAt(state.selection.main.head);
  if (line.to === state.doc.length) return false; // 已是末行
  const next = state.doc.lineAt(line.to + 1);
  const trailing = line.text.match(/\s+$/)?.[0].length ?? 0;
  const leading = next.text.match(/^\s+/)?.[0].length ?? 0;
  const joinAt = line.to - trailing;
  // 一次删除：行尾空格 + 换行 + 下行行首空格
  view.dispatch({
    changes: { from: joinAt, to: next.from + leading },
    selection: { anchor: joinAt },
    scrollIntoView: true,
  });
  return true;
};

const insertBlankAbove: Command = (view) => {
  const { state } = view;
  const line = state.doc.lineAt(state.selection.main.head);
  // 行首前插入换行即得空行；插入后 line.from 恰为新空行行首
  view.dispatch({
    changes: { from: line.from, insert: "\n" },
    selection: { anchor: line.from },
    scrollIntoView: true,
  });
  return true;
};

function insertSnippet(view: EditorView, text: string) {
  const { from, to } = view.state.selection.main;
  view.dispatch({
    changes: { from, to, insert: text },
    selection: { anchor: from + text.length },
    scrollIntoView: true,
  });
}

// Alt 插入类不能走 keymap 键名匹配：macOS 上纯 Option 组合的 event.key 是
// 产生的字符（Option+1 = ¡），CM6 对 mac 纯 Alt 又不做 base 键回退——绑
// "Alt-1" 永不命中，绑 "Alt-¡" 则随键盘布局漂移。改按物理键 event.code
// 判定，布局无关。
const altInsertHandler = EditorView.domEventHandlers({
  keydown(event, view) {
    if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return false;
    const digit = /^Digit([1-9])$/.exec(event.code);
    const text = digit ? `#(${digit[1]})` : event.code === "KeyZ" ? "#(增)" : null;
    if (text === null) return false;
    insertSnippet(view, text);
    event.preventDefault();
    return true;
  },
});

const killToLineEnd: Command = (view) => {
  const sel = view.state.selection.main;
  if (!sel.empty) {
    view.dispatch({ changes: { from: sel.from, to: sel.to } });
    return true;
  }
  const line = view.state.doc.lineAt(sel.head);
  const to = sel.head < line.to ? line.to : Math.min(view.state.doc.length, sel.head + 1);
  if (sel.head === to) return false;
  view.dispatch({ changes: { from: sel.head, to } });
  return true;
};

const killToLineStart: Command = (view) => {
  const sel = view.state.selection.main;
  if (!sel.empty) {
    view.dispatch({ changes: { from: sel.from, to: sel.to } });
    return true;
  }
  const line = view.state.doc.lineAt(sel.head);
  const from = sel.head > line.from ? line.from : Math.max(0, sel.head - 1);
  if (sel.head === from) return false;
  view.dispatch({ changes: { from, to: sel.head } });
  return true;
};

export const gujiKeymap = [
  Prec.highest(
    keymap.of([
      { key: "Ctrl-j", run: joinNextLine },
      { key: "Ctrl-o", run: insertBlankAbove },
      { key: "Ctrl-k", run: killToLineEnd },
      { key: "Ctrl-u", run: killToLineStart },
    ]),
  ),
  altInsertHandler,
];
