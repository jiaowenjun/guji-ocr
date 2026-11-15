// 编辑器快捷键（insert 模态方案；vim 开启后仅 insert 模态生效，normal 模态
// 让位给 vim 引擎——Ctrl-J/O/U 在 vim normal 下分别是下移一行/跳转列表/
// 上滚半屏）：
// Ctrl-J 下一行并入本行末尾——先去本行行尾空格与下一行行首空格（含全角），
//   删除中间换行完成拼接，光标落在接缝处。
// Ctrl-O 光标后插换行、光标不动（emacs open-line / 原生 NSTextView 语义，
//   新空行在下方；行中按即劈行）；Ctrl-Alt-O 本行上方插空行，光标不动
//   （列不变，随本行下移）。
// Ctrl-U 删光标到行首；已在行首时删前一换行（对称语义，同 CM deleteToLineStart；
//   macOS 文本系统无 ^U 原生绑定——那是 readline 键位——故须自实现）。
// Ctrl-K/A/E/F/B/N/P/D/H/T/V/W 等 emacs 键位经 WKWebView 原生生效，无需绑定。
// Alt/Option-Z 插入 #(增)，Alt/Option-X 插入 □，Alt/Option-数字插入 #(数字)
//   （如 Alt-1 → #(1)）；原生布局字符（≈/Ω/¡…）经 beforeinput 兜底吞掉。
// \s 含 U+3000 全角空格，无需另列。
import { Prec } from "@codemirror/state";
import { EditorView, keymap, type Command } from "@codemirror/view";
import { Vim, getCM } from "@replit/codemirror-vim";

// vim normal 模态 J → gJ：合并下一行时不在本行末尾插空格（.gj 行密排无行
// 首尾空白，与 gJ「保留下行行首空白」的差异实际不可见；count 前缀与 . 重
// 复随 keyToKey 重放保留）。ctx 限定 normal，visual J 维持引擎默认。
// keyToKey 映射经 unshift 进全局 keymap，所有编辑器实例按键时实时查表；
// 模块重复求值（HMR）会重复 unshift 同映射，命中首个，无害。
Vim.map("J", "gJ", "normal");

// vim normal 模态 I → ^i：绕开 enterInsertMode firstNonBlank 分支的代理对
// 修正器缺陷——光标停在高代理码元（康熙 Ext-B 字头常态，如 #𠃕 的 𠃕）上按
// I，正确的行首 {0,0} 会被 updateSelectionForSurrogateCharacters 误 +1 成
// {0,1}（守卫 curStart.ch >= curEnd.ch - 1 对同行后退移动恒真 + 高代理上界
// 笔误只认 0xD800–0xD8FF，Ext-B 全区中招）。^（motion）与 i（inplace）均不
// 过修正器，行为与 I 等价且保留计数前缀。复现与分析见 public/vim-i-bug.html。
Vim.map("I", "^i", "normal");

// vim 扩展激活且处于非 insert 模态（normal/visual 等）时本键位组让位。
// vim 插件经 DOM keydown 自行接管按键（不走 CM keymap），若不让位，
// Prec.highest 的绑定会在 normal 模态抢先命中（如 Ctrl-J 误合并行）。
const vimNormalMode = (view: EditorView): boolean => {
  const vim = getCM(view)?.state.vim;
  return vim != null && !vim.insertMode;
};

// 包装为「仅 insert 模态（或未开 vim）」执行；其余返回 false 放行给 vim
const insertOnly = (cmd: Command): Command => (view) =>
  vimNormalMode(view) ? false : cmd(view);

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

const openLineBelow: Command = (view) => {
  const { head } = view.state.selection.main;
  // 光标处插换行、光标不动（位于插入点的选区按映射保持原位）
  view.dispatch({ changes: { from: head, insert: "\n" } });
  return true;
};

const insertLineAboveKeepCursor: Command = (view) => {
  const { state } = view;
  const { head } = state.selection.main;
  const line = state.doc.lineAt(head);
  // 行首前插换行；本行整体下移一行，光标 +1 即保持原列不动
  view.dispatch({
    changes: { from: line.from, insert: "\n" },
    selection: { anchor: head + 1 },
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
// 另外 WKWebView/输入注入管线（CDP text 等）对 Option 组合的字符插入可能
// 绕过 keydown preventDefault 直插文本（实测 Alt-X 出 ≈□），在 beforeinput
// 再拦一道——只吞 Alt 按住时的 US 布局 Option 字符（皆为快捷键键位的产物，
// .gj 文本中不会合法出现）。
const altInserts: Record<string, string | undefined> = { KeyZ: "#(增)", KeyX: "□" };
const optionChars = new Set(["≈", "Ω", "¡", "™", "£", "¢", "∞", "§", "¶", "•", "ª"]);
const altInsertHandler = EditorView.domEventHandlers({
  keydown(event, view) {
    if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return false;
    if (vimNormalMode(view)) return false; // normal 模态归 vim：Alt 键未被映射，布局字符由 beforeinput 兜底
    const digit = /^Digit([1-9])$/.exec(event.code);
    const text = digit ? `#(${digit[1]})` : altInserts[event.code];
    if (text === undefined) return false;
    insertSnippet(view, text);
    event.preventDefault();
    return true;
  },
  beforeinput(event) {
    // InputEvent 无 altKey 可读（修饰键非 UIEvent 属性），按字符判——
    // 全组皆为快捷键键位的布局产物，.gj 文本不会合法包含
    if (event.inputType === "insertText" && event.data != null && optionChars.has(event.data)) {
      event.preventDefault();
      return true;
    }
    return false;
  },
});

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
      { key: "Ctrl-j", run: insertOnly(joinNextLine) },
      { key: "Ctrl-o", run: insertOnly(openLineBelow) },
      { key: "Ctrl-Alt-o", run: insertOnly(insertLineAboveKeepCursor) },
      { key: "Ctrl-u", run: insertOnly(killToLineStart) },
    ]),
  ),
  altInsertHandler,
];
