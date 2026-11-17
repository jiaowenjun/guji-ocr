// @vitest-environment jsdom
import { act, createElement, createRef } from "react";
import { createRoot } from "react-dom/client";
import { EditorView } from "@codemirror/view";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GujiEditor, type GujiEditorHandle } from "../src/components/editor/GujiEditor";

Object.defineProperties(Range.prototype, {
  getClientRects: { configurable: true, value: () => [] },
  getBoundingClientRect: { configurable: true, value: () => new DOMRect() },
});

const source = "@1\n\n#𠀤甲乙\n";
let container: HTMLDivElement;
let root: ReturnType<typeof createRoot>;
const editor = createRef<GujiEditorHandle>();
const onCursor = vi.fn();

beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  onCursor.mockClear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  await act(async () => root.render(createElement(GujiEditor, {
    ref: editor, value: source, onChange: () => {}, onCursor,
  })));
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe("编辑器定位命令", () => {
  it("重复定位同一 UTF-16 位置可恢复光标、折叠选区并重新聚焦", async () => {
    const view = EditorView.findFromDOM(container.querySelector(".cm-content")!)!;
    const target = source.indexOf("𠀤") + 2;
    await act(async () => editor.current!.revealPosition(target));
    expect(view.state.selection.main.head).toBe(target);
    await act(async () => view.dispatch({ selection: { anchor: source.indexOf("乙") + 1 } }));
    await act(async () => editor.current!.revealPosition(target));
    expect(view.state.selection.main.head).toBe(target);
    expect(onCursor).toHaveBeenLastCalledWith(target);

    await act(async () => {
      view.dispatch({ selection: { anchor: 0, head: target } });
      view.contentDOM.blur();
      editor.current!.revealPosition(target);
    });
    expect(view.state.selection.main.empty).toBe(true);
    expect(view.state.selection.main.head).toBe(target);
    expect(view.hasFocus).toBe(true);
  });

  it("换入短文档后定位命令使用当前文档范围", async () => {
    const value = "@2\n";
    await act(async () => root.render(createElement(GujiEditor, {
      ref: editor, value, onChange: () => {}, onCursor,
    })));
    await act(async () => editor.current!.revealPosition(source.length));
    expect(onCursor).toHaveBeenLastCalledWith(value.length);
  });
});
