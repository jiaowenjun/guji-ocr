// 编辑器快捷键：
// Ctrl-J 下一行并入本行末尾——先去本行行尾空格与下一行行首空格（含全角），
//   删除中间换行完成拼接，光标落在接缝处；
// Ctrl-O 在本行上方插入空行，光标移到空行行首。
// \s 含 U+3000 全角空格，无需另列。
import { Prec } from "@codemirror/state";
import { keymap, type Command } from "@codemirror/view";

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

export const gujiKeymap = Prec.highest(
  keymap.of([
    { key: "Ctrl-j", run: joinNextLine },
    { key: "Ctrl-o", run: insertBlankAbove },
  ]),
);
