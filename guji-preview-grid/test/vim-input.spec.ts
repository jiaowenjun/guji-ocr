// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { EditorView } from "@codemirror/view";
import { StateEffect } from "@codemirror/state";
import { getCM, vim } from "@replit/codemirror-vim";
import { vimInputGuard } from "@/components/editor/vim-input";
import { gujiKeymap } from "@/components/editor/keymap";

// jsdom 不提供文字布局；这里只测事件、模态和文档，真实光标几何另在浏览器验证。
Object.defineProperties(Range.prototype, {
  getClientRects: { configurable: true, value: () => [] },
  getBoundingClientRect: { configurable: true, value: () => new DOMRect() },
});

const original = "一行字\n二行字\n三行字\n";
const extensions = () => [vim(), vimInputGuard, gujiKeymap];
const views: EditorView[] = [];

function makeView(enabled = true) {
  const view = new EditorView({
    doc: original,
    parent: document.body,
    extensions: enabled ? extensions() : [gujiKeymap],
  });
  views.push(view);
  return view;
}

async function key(view: EditorView, key: string) {
  view.contentDOM.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  await Promise.resolve(); // 模态信号的 DOM 同步
}

function composition(view: EditorView, type: string, data = "") {
  view.contentDOM.dispatchEvent(new CompositionEvent(type, { data, bubbles: true }));
}

function beforeInput(view: EditorView, data: string, cancelable = true) {
  const event = new InputEvent("beforeinput", {
    inputType: "insertCompositionText", data, isComposing: true, bubbles: true, cancelable,
  });
  view.contentDOM.dispatchEvent(event);
  return event;
}

// 模拟 IME 已经写进 DOM 的预编辑文本，走真正的 MutationObserver/inputHandler，
// 而非直接 dispatch 文档事务（后者本来就必须允许 Vim 命令和外部加载改文档）。
function mutateFirstLine(view: EditorView, prefix: string) {
  const text = view.contentDOM.querySelector(".cm-line")!.firstChild as Text;
  text.data = prefix + original.split("\n")[0];
}

afterEach(() => {
  for (const view of views.splice(0)) view.destroy();
});

describe("Vim 与中文输入法", () => {
  it("normal 保持可聚焦并处理 jj 命令；insert/normal 切换原生输入入口", async () => {
    const view = makeView();
    view.focus();
    expect(view.hasFocus).toBe(true);
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("false");
    await key(view, "j");
    await key(view, "j");
    expect(view.state.selection.main.head).toBeGreaterThan(0);
    expect(view.state.doc.toString()).toBe(original);
    await key(view, "i");
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("true");
    await key(view, "Escape");
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("false");
    expect(view.hasFocus).toBe(true);
  });

  it.each(["j", "jj", "中文"])("normal 拦截不可取消的预编辑 DOM 写入 %s", async (text) => {
    const view = makeView();
    composition(view, "compositionstart");
    beforeInput(view, text, false);
    mutateFirstLine(view, text);
    await vi.waitFor(() => {
      expect(view.contentDOM.querySelector(".cm-line")!.textContent).toBe("一行字");
    });
    composition(view, "compositionend", text);
    expect(view.state.doc.toString()).toBe(original);
    expect(view.state.selection.main.head).toBe(0);
  });

  it("visual 跨行选区不会被 compositionstart 删除", async () => {
    const view = makeView();
    await key(view, "v");
    await key(view, "j");
    const selection = view.state.selection;
    expect(selection.main.to).toBeGreaterThan(view.state.doc.line(1).to);
    composition(view, "compositionstart");
    expect(beforeInput(view, "jj").defaultPrevented).toBe(true);
    expect(view.state.doc.toString()).toBe(original);
    expect(view.state.selection.eq(selection)).toBe(true);
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("false");
  });

  it.each([true, false])("insert 或未启用 Vim 时照常接收中文预编辑和提交（Vim=%s）", async (enabled) => {
    const view = makeView(enabled);
    if (enabled) await key(view, "i");
    composition(view, "compositionstart");
    expect(beforeInput(view, "zhong").defaultPrevented).toBe(false);
    mutateFirstLine(view, "zhong");
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe("zhong" + original));
    beforeInput(view, "中", false);
    mutateFirstLine(view, "中");
    composition(view, "compositionend", "中");
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe("中" + original));
  });

  it("normal 的 x/dd/p 仍可编辑，程序加载文档也不受阻", async () => {
    const view = makeView();
    await key(view, "x");
    expect(view.state.doc.toString()).toBe(original.slice(1));
    await key(view, "d");
    await key(view, "d");
    expect(view.state.doc.toString()).toBe("二行字\n三行字\n");
    await key(view, "p");
    expect(view.state.doc.toString()).toBe("二行字\n行字\n三行字\n");
    view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: original } });
    expect(view.state.doc.toString()).toBe(original);
  });

  it.each(["f", "r"])("%s 等待字面字符时开放输入，命令完成后关闭", async (command) => {
    const view = makeView();
    await key(view, command);
    expect(getCM(view)?.state.vim?.expectLiteralNext).toBe(true);
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("true");
    await key(view, "字");
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("false");
    if (command === "f") {
      expect(view.state.selection.main.head).toBe(2);
      expect(view.state.doc.toString()).toBe(original);
    } else {
      expect(view.state.doc.toString()).toBe("字" + original.slice(1));
    }
  });

  it("整树 reconfigure 保留 insert 可编辑性，关闭 Vim 恢复普通输入", async () => {
    const view = makeView();
    await key(view, "i");
    view.dispatch({ effects: StateEffect.reconfigure.of(extensions()) });
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("true");
    await key(view, "Escape");
    view.dispatch({ effects: StateEffect.reconfigure.of([gujiKeymap]) });
    await Promise.resolve();
    expect(view.contentDOM.getAttribute("contenteditable")).toBe("true");
    composition(view, "compositionstart");
    expect(beforeInput(view, "中文").defaultPrevented).toBe(false);
    mutateFirstLine(view, "中文");
    composition(view, "compositionend", "中文");
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe("中文" + original));
  });
});
