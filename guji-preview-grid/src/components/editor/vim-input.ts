import { Compartment, Prec } from "@codemirror/state";
import { EditorView, ViewPlugin } from "@codemirror/view";
import { getCM } from "@replit/codemirror-vim";

function acceptsText(view: EditorView): boolean {
  const vim = getCM(view)?.state.vim;
  // f/F/t/T/r 等命令等待字面字符时仍须允许中文输入法。
  return !vim || vim.insertMode || !!vim.expectLiteralNext;
}

const editable = new Compartment();
const modeEvents = ["vim-mode-change", "vim-keypress", "vim-command-done"];

const inputMode = ViewPlugin.fromClass(class {
  private cm;
  private view: EditorView;
  private pending = false;
  private destroyed = false;

  constructor(view: EditorView) {
    this.view = view;
    this.cm = getCM(view);
    for (const event of modeEvents) this.cm?.on(event, this.sync);
    view.contentDOM.addEventListener("compositionstart", this.onCompositionStart, true);
    this.sync();
  }

  // 模态信号可能在 CM 更新中发出；微任务在当前按键结束后同步 DOM 可编辑性，
  // 避免嵌套 dispatch。只关闭原生输入，不用 readOnly（x/dd/p 等仍须改文档）。
  private sync = () => {
    if (this.pending || this.destroyed) return;
    this.pending = true;
    queueMicrotask(() => {
      this.pending = false;
      if (this.destroyed) return;
      const allow = acceptsText(this.view);
      if (this.view.state.facet(EditorView.editable) !== allow) {
        this.view.dispatch({ effects: editable.reconfigure(EditorView.editable.of(allow)) });
      }
    });
  };

  private onCompositionStart = (event: CompositionEvent) => {
    if (acceptsText(this.view)) return;
    // compositionstart 不可取消，但须先于 CM 的 composition observer 拦截：
    // 后者会在组合输入开始时删除跨行选区，visual 模态也会受影响。
    event.stopImmediatePropagation();
  };

  update() {
    this.sync();
  }

  destroy() {
    this.destroyed = true;
    for (const event of modeEvents) this.cm?.off(event, this.sync);
    this.view.contentDOM.removeEventListener("compositionstart", this.onCompositionStart, true);
  }
});

// 与 vim() 一起挂载，顺序在其后。normal/visual 下关闭 contenteditable，
// 使 macOS 不启动拼音预编辑；tabindex 保持聚焦、Vim 命令和鼠标选区可用。
export const vimInputGuard = [
  editable.of(EditorView.editable.of(false)),
  EditorView.contentAttributes.of({ tabindex: "0" }),
  inputMode,
  Prec.highest(EditorView.domEventHandlers({
    beforeinput(event, view) {
      if (acceptsText(view)) return false;
      event.preventDefault();
      return true;
    },
  })),
  // beforeinput 在 macOS IME 中不一定可取消。上游仅消费部分单字符输入，
  // 多字符预编辑（如 jj）会落入默认插入路径；在它之后拦住 DOM 写入兜底。
  Prec.lowest(EditorView.inputHandler.of((view) => !acceptsText(view))),
];
