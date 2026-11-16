// vim 模式集成测试：@replit/codemirror-vim 与 guji 键位的模态让位协议。
// 口径：vim 开启 → 初始 normal；normal 下 emacs/Alt 键位让位（Ctrl-J 不合并行、
// Alt-Z 不插入糖）；i 进入 insert 后现有方案照常（Ctrl-J 合并行、Alt-Z 插入）；
// Esc 返回 normal；vim 未开启时行为与从前完全一致。
// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { EditorView } from "@codemirror/view";
import { StateEffect, type Extension } from "@codemirror/state";
import { vim, getCM } from "@replit/codemirror-vim";
import { gujiKeymap } from "@/components/editor/keymap";

function makeView(extensions: Extension[]): EditorView {
  return new EditorView({
    doc: "一行字\n二行字\n",
    parent: document.body,
    extensions,
  });
}

/** 派发真实 keydown 到 contentDOM（CM keymap 与 vim 插件都监听此事件） */
function key(view: EditorView, k: string, init: KeyboardEventInit = {}) {
  view.contentDOM.dispatchEvent(
    new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...init }),
  );
}

const ctrlJ = (view: EditorView) => key(view, "j", { ctrlKey: true });
const doc = (view: EditorView) => view.state.doc.toString();
const insertMode = (view: EditorView) => !!getCM(view)?.state.vim?.insertMode;

const views: EditorView[] = [];
const track = (view: EditorView) => (views.push(view), view);

afterEach(() => {
  for (const v of views.splice(0)) v.destroy();
});

describe("vim 关闭（默认）：emacs 键位原样", () => {
  it("Ctrl-J 合并下一行", () => {
    const view = track(makeView([gujiKeymap]));
    ctrlJ(view);
    expect(doc(view)).toBe("一行字二行字\n");
  });
});

describe("vim 开启：模态协议", () => {
  it("初始为 normal，i 进 insert、Esc 回 normal", () => {
    const view = track(makeView([vim(), gujiKeymap]));
    expect(insertMode(view)).toBe(false);
    key(view, "i");
    expect(insertMode(view)).toBe(true);
    key(view, "Escape");
    expect(insertMode(view)).toBe(false);
  });

  it("normal 模态 Ctrl-J 让位给 vim（文档不变，不再合并行）", () => {
    const view = track(makeView([vim(), gujiKeymap]));
    ctrlJ(view);
    expect(doc(view)).toBe("一行字\n二行字\n");
  });

  it("insert 模态保留现有方案：Ctrl-J 合并行、Alt-Z 插入 #(增)", () => {
    const view = track(makeView([vim(), gujiKeymap]));
    key(view, "i");
    ctrlJ(view);
    expect(doc(view)).toBe("一行字二行字\n");
    key(view, "z", { altKey: true, code: "KeyZ" });
    expect(doc(view)).toContain("#(增)");
  });

  it("normal 模态 Alt-Z 让位（不插入糖）", () => {
    const view = track(makeView([vim(), gujiKeymap]));
    key(view, "z", { altKey: true, code: "KeyZ" });
    expect(doc(view)).toBe("一行字\n二行字\n");
  });

  it("normal 模态 J 合并不插空格（J→gJ 映射），计数前缀保留", () => {
    // 三行密排：J 应纯边界拼接（无 " " 注入）；3J 一次并起两行
    const view = track(
      new EditorView({ doc: "一行\n二行\n三行\n", parent: document.body, extensions: [vim(), gujiKeymap] }),
    );
    key(view, "J");
    expect(doc(view)).toBe("一行二行\n三行\n");
    key(view, "3");
    key(view, "J");
    // 3J 三行并作一行：末尾 \n 是空行，一并被吞（vim J 语义），尾换行消失
    expect(doc(view)).toBe("一行二行三行");
  });

  it("normal 模态吞掉原生 emacs 泄漏键（Ctrl-K 等），insert 模态与 vim 关闭时放行", () => {
    // 泄漏键（引擎未绑定、WKWebView 有原生编辑行为）：Ctrl-G/H/J/K/L/S/T——
    // normal/visual 模态须 preventDefault 吞掉（防原生 ^K 杀行尾、^T 交换等
    // 破坏文档），insert 模态与 vim 关闭时返回 false 原生照常。
    const leaks = ["g", "h", "j", "k", "l", "s", "t"];
    const dispatch = (view: EditorView, k: string) => {
      const ev = new KeyboardEvent("keydown", { key: k, ctrlKey: true, bubbles: true, cancelable: true });
      view.contentDOM.dispatchEvent(ev);
      return ev.defaultPrevented;
    };

    const view = track(makeView([vim(), gujiKeymap]));
    for (const k of leaks) {
      expect(dispatch(view, k), `normal 模态 Ctrl-${k} 应被吞掉`).toBe(true);
      expect(doc(view), `normal 模态 Ctrl-${k} 不应改动文档`).toBe("一行字\n二行字\n");
    }
    key(view, "i");
    // insert 放行集不含引擎有 insert 绑定的键：Ctrl-T/D/U/W/J 分别是 vim 的
    // i_CTRL-T 缩进/去缩进/删行/删词等（Ctrl-J 则是本应用并行动作）——vim
    // insert 语义，吞键逻辑不干预
    for (const k of ["g", "h", "k", "l", "s"]) {
      expect(dispatch(view, k), `insert 模态 Ctrl-${k} 应放行给原生`).toBe(false);
    }
    // Ctrl-J 在 insert 模态是本应用自己的并行动作（非原生），照常消费
    expect(dispatch(view, "j"), "insert 模态 Ctrl-J 由并行动作消费").toBe(true);
    const plain = track(makeView([gujiKeymap]));
    // vim 关闭时吞键恒 false；Ctrl-J 同理是本应用命令（与非 vim 现状一致）
    for (const k of ["g", "h", "k", "l", "s", "t"]) {
      expect(dispatch(plain, k), `vim 关闭时 Ctrl-${k} 应放行给原生`).toBe(false);
    }
  });

  it("normal 模态 I 落行首：高代理位光标不再被修正器掰偏（I→^i 映射）", () => {
    // 上游缺陷：#𠃕 的 𠃕 是 Ext-B 代理对，光标盖在高代理位（head=1）按 I，
    // firstNonBlank 的 {0,0} 会被 updateSelectionForSurrogateCharacters 误 +1
    // 成 {0,1}（落在 # 之后）。映射 ^i 绕开修正器，行为等价。
    const view = track(
      new EditorView({ doc: "#𠃕\n", parent: document.body, extensions: [vim(), gujiKeymap] }),
    );
    view.dispatch({ selection: { anchor: 1 } });
    key(view, "I");
    expect(insertMode(view)).toBe(true);
    expect(view.state.selection.main.head).toBe(0);
  });

  it("整树 reconfigure（@uiw 每渲染路径）不打断模态", () => {
    // vim() 各段为包内模块级常量：即便每次调用重新组装、reconfigure 整组
    // extensions，CM6 按插件 spec 身份保活实例，insert 模态不丢——这是
    // extensions 每渲染重建（现状风格）可行的依据。
    const view = track(makeView([vim(), gujiKeymap]));
    key(view, "a"); // append 进入 insert
    expect(insertMode(view)).toBe(true);
    view.dispatch({
      effects: StateEffect.reconfigure.of([vim(), gujiKeymap]),
    });
    expect(insertMode(view)).toBe(true);
    key(view, "Escape");
    expect(insertMode(view)).toBe(false);
  });
});
