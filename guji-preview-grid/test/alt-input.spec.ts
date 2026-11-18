// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EditorView } from "@codemirror/view";
import { StateEffect } from "@codemirror/state";
import { getCM, vim } from "@replit/codemirror-vim";
import { gujiKeymap } from "@/components/editor/keymap";
import { vimInputGuard } from "@/components/editor/vim-input";

Object.defineProperties(Range.prototype, {
  getClientRects: { configurable: true, value: () => [] },
  getBoundingClientRect: { configurable: true, value: () => new DOMRect() },
});

const views: EditorView[] = [];
const extensions = (enabled: boolean) => enabled ? [vim(), vimInputGuard, gujiKeymap] : [gujiKeymap];
async function makeView(enabled = true) {
  const view = new EditorView({ doc: "甲乙丙", parent: document.body, extensions: extensions(enabled) });
  views.push(view);
  view.focus();
  if (enabled) key(view, "i");
  await Promise.resolve();
  return view;
}

function key(view: EditorView, key: string, init: KeyboardEventInit = {}, type = "keydown") {
  const event = new KeyboardEvent(type, { key, bubbles: true, cancelable: true, ...init });
  view.contentDOM.dispatchEvent(event);
  return event;
}
const optionDown = (view: EditorView) => key(view, "Alt", { code: "AltLeft", keyCode: 18, altKey: true });
const optionUp = (view: EditorView) => key(view, "Alt", { code: "AltLeft", keyCode: 18 }, "keyup");
const editable = (view: EditorView) => view.contentDOM.getAttribute("contenteditable");

beforeEach(() => {
  vi.spyOn(navigator, "platform", "get").mockReturnValue("MacIntel");
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/27.2 Safari/605.1.15");
});
afterEach(() => {
  for (const view of views.splice(0)) view.destroy();
  vi.restoreAllMocks();
});

describe("Safari Option 快捷键与拼音", () => {
  it.each([true, false])("在数字到达前关闭原生输入，保留选区/焦点和保存（Vim=%s）", async (enabled) => {
    const view = await makeView(enabled);
    view.dispatch({ selection: { anchor: 1, head: 2 } });
    const blur = vi.fn();
    view.contentDOM.addEventListener("blur", blur);
    optionDown(view);
    // 原生复测确认：该 DOM 状态让 WebKit 对后续数字跳过拼音，keyCode 从 229 变为 52。
    // jsdom 检验输入入口契约；候选窗是否消失仍需原生键盘验证。
    expect(editable(view)).toBe("false");
    expect(view.state.facet(EditorView.editable)).toBe(true);
    expect(view.hasFocus).toBe(true);
    await Promise.resolve(); // Vim 守卫不能把暂停状态恢复或陷入 reconfigure 循环
    expect(editable(view)).toBe("false");
    expect(key(view, "4", { code: "Digit4", keyCode: 52, altKey: true }).defaultPrevented).toBe(true);
    expect(view.state.doc.toString()).toBe("甲#(4)丙");
    expect(view.state.selection.main.anchor).toBe(5);
    expect(view.state.selection.main.empty).toBe(true);
    expect(editable(view)).toBe("false"); // 文档更新不能提前恢复输入
    optionUp(view);
    expect(editable(view)).toBe("true");
    expect(view.hasFocus).toBe(true);
    expect(blur).not.toHaveBeenCalled();
    if (enabled) expect(getCM(view)?.state.vim?.insertMode).toBe(true);

    let saves = 0;
    const save = (event: KeyboardEvent) => {
      if (event.metaKey && event.key === "s") { event.preventDefault(); saves++; }
    };
    window.addEventListener("keydown", save);
    try {
      expect(key(view, "s", { code: "KeyS", metaKey: true }).defaultPrevented).toBe(true);
      expect(saves).toBe(1);
      expect(view.state.doc.toString()).toBe("甲#(4)丙");
    } finally {
      window.removeEventListener("keydown", save);
    }
  });

  it("按住 Option 连续插入数字/增/缺字符号，松开后接收正常拼音", async () => {
    const view = await makeView();
    optionDown(view);
    for (const n of [1, 4, 9]) key(view, String(n), { code: `Digit${n}`, altKey: true });
    key(view, "Ω", { code: "KeyZ", altKey: true });
    key(view, "≈", { code: "KeyX", altKey: true });
    expect(view.state.doc.toString()).toBe("#(1)#(4)#(9)#(增)□甲乙丙");
    expect(editable(view)).toBe("false");
    optionUp(view);
    view.contentDOM.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true }));
    const input = new InputEvent("beforeinput", {
      inputType: "insertCompositionText", data: "zhong", isComposing: true, bubbles: true, cancelable: false,
    });
    view.contentDOM.dispatchEvent(input);
    expect(input.defaultPrevented).toBe(false);
    const node = view.contentDOM.querySelector(".cm-line")!.firstChild as Text;
    node.data = "#(1)#(4)#(9)#(增)□zhong甲乙丙";
    await vi.waitFor(() => expect(view.state.doc.toString()).toContain("zhong"));
    node.data = "#(1)#(4)#(9)#(增)□中甲乙丙";
    view.contentDOM.dispatchEvent(new CompositionEvent("compositionend", { data: "中", bubbles: true }));
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe("#(1)#(4)#(9)#(增)□中甲乙丙"));
  });

  it("未绑定的 Option 组合在 keydown 中恢复原生输入，不被吞掉", async () => {
    const view = await makeView();
    optionDown(view);
    expect(editable(view)).toBe("false");
    expect(key(view, "å", { code: "KeyA", altKey: true }).defaultPrevented).toBe(false);
    expect(editable(view)).toBe("true");
    const input = new InputEvent("beforeinput", { inputType: "insertText", data: "å", bubbles: true, cancelable: true });
    view.contentDOM.dispatchEvent(input);
    expect(input.defaultPrevented).toBe(false);
    const node = view.contentDOM.querySelector(".cm-line")!.firstChild as Text;
    node.data = "å甲乙丙";
    await vi.waitFor(() => expect(view.state.doc.toString()).toBe("å甲乙丙"));
  });

  it("增加其他修饰键时恢复输入，保留 Ctrl-Alt 等组合键", async () => {
    const view = await makeView();
    optionDown(view);
    key(view, "Control", { code: "ControlLeft", altKey: true, ctrlKey: true });
    expect(editable(view)).toBe("true");
    expect(view.state.doc.toString()).toBe("甲乙丙");
  });

  it("松开 Option 的事件丢失时，失焦或下一个普通键会恢复输入", async () => {
    const view = await makeView();
    optionDown(view);
    view.contentDOM.blur();
    expect(editable(view)).toBe("true");
    view.focus();
    optionDown(view);
    key(view, "a", { code: "KeyA" });
    expect(editable(view)).toBe("true");
  });

  it("Vim normal 和等待字面字符时不暂停输入，Esc 后保持 normal 不可编辑", async () => {
    const view = await makeView();
    optionDown(view);
    key(view, "Escape", { altKey: true });
    // 带 Alt 的 Escape 让位于 Vim；再按普通 Escape 回 normal。
    key(view, "Escape");
    await Promise.resolve();
    expect(getCM(view)?.state.vim?.insertMode).toBe(false);
    optionUp(view);
    optionDown(view);
    optionUp(view);
    expect(editable(view)).toBe("false");
    key(view, "f");
    await Promise.resolve();
    expect(editable(view)).toBe("true");
    optionDown(view);
    expect(editable(view)).toBe("true");
    optionUp(view);
  });

  it.each([[true, false], [false, true], [true, true]])(
    "已有组合输入不暂停、不抢占 Option 数字（event=%s，view=%s）", async (eventComposing, viewComposing) => {
      const view = await makeView();
      if (viewComposing) view.contentDOM.dispatchEvent(new CompositionEvent("compositionstart", { bubbles: true }));
      key(view, "Alt", { altKey: true, isComposing: eventComposing });
      expect(editable(view)).toBe("true");
      expect(key(view, "4", { code: "Digit4", altKey: true, isComposing: eventComposing }).defaultPrevented).toBe(false);
      expect(view.state.doc.toString()).toBe("甲乙丙");
      view.contentDOM.dispatchEvent(new CompositionEvent("compositionend", { bubbles: true }));
    },
  );

  it("React 扩展 reconfigure 保留暂停，卸载快捷键扩展后恢复输入", async () => {
    const view = await makeView();
    optionDown(view);
    view.dispatch({ effects: StateEffect.reconfigure.of(extensions(true)) });
    expect(editable(view)).toBe("false");
    expect(getCM(view)?.state.vim?.insertMode).toBe(true);
    view.dispatch({ effects: StateEffect.reconfigure.of([vim(), vimInputGuard]) });
    expect(editable(view)).toBe("true");
  });

  it.each([
    ["MacIntel", "Mozilla/5.0 AppleWebKit/537.36 Chrome/156 Safari/537.36"],
    ["MacIntel", "Mozilla/5.0 Gecko/20100101 Firefox/140"],
    ["Linux x86_64", "Mozilla/5.0 AppleWebKit/605.1.15"],
  ])("不改动其他浏览器的原生入口（%s，%s）", async (platform, ua) => {
    vi.spyOn(navigator, "platform", "get").mockReturnValue(platform);
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue(ua);
    const view = await makeView();
    optionDown(view);
    expect(editable(view)).toBe("true");
    expect(key(view, "4", { code: "Digit4", altKey: true }).defaultPrevented).toBe(true);
    expect(view.state.doc.toString()).toBe("#(4)甲乙丙");
  });
});
