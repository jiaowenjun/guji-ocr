// @vitest-environment jsdom
import { act, createElement, useImperativeHandle, type ComponentProps, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DatasetView } from "../src/components/dataset/DatasetView";
import type { GujiEditor } from "../src/components/editor/GujiEditor";
import { KANGXI_DATASET } from "../src/datasets/kangxi";

// 真实 DatasetView → IR → MatrixPages；只替换编辑器输入和无布局能力的外壳。
let editor: ComponentProps<typeof GujiEditor>;
const revealPosition = vi.fn();
let headwordRenders = 0;
vi.mock("../src/components/editor/GujiEditor", () => ({
  GujiEditor: (props: ComponentProps<typeof GujiEditor>) => {
    editor = props;
    useImperativeHandle(props.ref, () => ({ revealPosition }), []);
    return null;
  },
}));
vi.mock("../src/components/dataset/HeadwordStrip", () => ({ HeadwordStrip: () => {
  headwordRenders++;
  return null;
} }));
vi.mock("../src/components/ui/resizable", () => {
  const panel = ({ children }: { children: ReactNode }) => createElement("div", null, children);
  return { ResizablePanelGroup: panel, ResizablePanel: panel, ResizableHandle: () => null };
});

const sources: Record<number, string> = { 1: "@1\n\n#甲乙\n", 2: "@2\n\n#戊己\n" };
let root: Root;
let container: HTMLDivElement;

beforeEach(async () => {
  revealPosition.mockReset().mockImplementation((position: number) => editor.onCursor?.(position));
  headwordRenders = 0;
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("ResizeObserver", class {
    observe() {}
    unobserve() {}
    disconnect() {}
  });
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/dataset/page-tool" && JSON.parse(String(init?.body)).action === "dataset-index") return {
      ok: true,
      json: async () => ({ ok: true, config: KANGXI_DATASET, pages: [1, 2].map((page) => ({
        page, image: `${page}.jpg`, width: 1130, height: 1679,
      })) }),
    };
    const page = Number(/\/(\d+)\.gj$/.exec(url)?.[1]);
    if (!(page in sources)) throw new Error(`Unexpected fetch: ${url}`);
    return { ok: true, text: async () => sources[page] };
  }));
  // 不推进时间：任何重新引入的延迟布局都会让下面的行为断言失败。
  vi.useFakeTimers();
  const toolbar = document.createElement("div");
  toolbar.id = "app-toolbar-slot";
  container = document.createElement("div");
  document.body.append(toolbar, container);
  root = createRoot(container);
  await act(async () => root.render(createElement(DatasetView)));
});

afterEach(async () => {
  await act(async () => root.unmount());
  document.body.replaceChildren();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const activeText = () => container.querySelector(".m-char-active")?.textContent;

// 浏览器双击的真实事件顺序；可抓住先冒泡到列首、再定位单字的闪跳。
async function doubleClick(element: Element) {
  for (const detail of [1, 2]) {
    for (const type of ["mousedown", "mouseup", "click"]) {
      await act(async () => {
        element.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, detail }));
      });
      expect(revealPosition).not.toHaveBeenCalled();
    }
  }
  await act(async () => {
    element.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true, detail: 2 }));
  });
}

describe("数据集预览使用当前文档快照", () => {
  it.each([
    ["大字扩展区", "@1\n#甲𠀤乙", ".m-large", "𠀤", "𠀤"],
    ["书名中的重复字", "@1\n#甲\n甲。乙【甲】丙", ".m-cell", "甲", "甲"],
    ["小字扩展区", "@1\n#甲\n乙。𠀀丙", ".m-cell", "𠀀", "𠀀"],
    ["小字空位", "@1\n#甲\n乙。*丙", ".m-cell", " ", "*"],
    ["大字空位", "@1\n#甲*乙", ".m-large", " ", "*"],
    ["归一圈号", "@1\n#甲\n乙。〇丙", ".m-cell", "○", "〇"],
    ["圈内数字合字", "@1\n#甲(15)乙", ".m-ring .stack", "十五", "1"],
    ["圈内扩展区合字", "@1\n#甲(𠀀乙)丙", ".m-ring .stack", "𠀀乙", "𠀀"],
    ["自动跨列", `@1\n${"甲".repeat(48)}。\n【𠀀】乙丙`, ".m-cell", "𠀀", "𠀀"],
  ])("双击%s定位到准确源码，且不触发列首定位", async (_name, source, selector, glyph, raw) => {
    await act(async () => editor.onChange(source));
    const element = [...container.querySelectorAll(selector)].filter(el => el.textContent === glyph).at(-1)!;
    expect(element).toBeDefined();
    await doubleClick(element);
    expect(revealPosition.mock.calls).toEqual([[source.lastIndexOf(raw) + raw.length]]);
    expect(activeText()).toBe(glyph);
    expect(editor.value).toBe(source);
  });

  it("重复双击、插字重排后使用当前源码；页面留白不触发字符定位", async () => {
    const initial = "@1\n#甲\n【甲乙】丙";
    await act(async () => editor.onChange(initial));
    const target = () => [...container.querySelectorAll(".m-cell")].find(el => el.textContent === "乙")!;
    await doubleClick(target());
    expect(revealPosition).toHaveBeenLastCalledWith(initial.indexOf("乙") + 1);
    expect(container.querySelector(".m-book-active")).not.toBeNull();
    revealPosition.mockClear();
    await act(async () => editor.onCursor!(initial.length));
    await doubleClick(target());
    expect(revealPosition.mock.calls).toEqual([[initial.indexOf("乙") + 1]]);

    const edited = "@1\n#𠀀$\n#甲\n甲" + "丙".repeat(48) + "【甲乙】丁";
    await act(async () => editor.onChange(edited));
    revealPosition.mockClear();
    await doubleClick(target());
    expect(revealPosition.mock.calls).toEqual([[edited.indexOf("乙") + 1]]);
    expect(activeText()).toBe("乙");
    revealPosition.mockClear();
    await doubleClick(container.querySelector(".m-lines")!);
    expect(revealPosition).not.toHaveBeenCalled();
  });

  it("原图字格紧邻字格开关，两个开关独立控制", async () => {
    const button = [...document.querySelectorAll<HTMLButtonElement>("button")].find((b) => b.textContent === "原图字格开")!;
    const matrixButton = button.previousElementSibling as HTMLButtonElement;
    expect(matrixButton.textContent).toBe("字格开");
    expect(button.getAttribute("aria-pressed")).toBe("true");
    await act(async () => button.click());
    expect(button.textContent).toBe("原图字格关");
    expect(container.querySelector("[data-scan-grid]")).toBeNull();
    expect(container.querySelector(".m-lines")?.getAttribute("data-cells")).toBe("on");
    await act(async () => matrixButton.click());
    expect(container.querySelector(".m-lines")?.getAttribute("data-cells")).toBe("off");
    await act(async () => button.click());
    expect(container.textContent).toContain("正在定位原图字格");
    expect(container.querySelector(".m-lines")?.getAttribute("data-cells")).toBe("off");
  });

  it("渲染空格对照独立显示、与原图共用请求，同占格编辑即时更新且切页清除旧结果", async () => {
    const originalFetch = fetch;
    const pending: { signal: AbortSignal; resolve: (response: unknown) => void }[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => url === "/dataset/scan-grid"
      ? new Promise(resolve => pending.push({ signal: init!.signal!, resolve }))
      : originalFetch(url, init)));
    const source = `@1\n${"甲".repeat(22)}*甲\n${"乙".repeat(23)}*`;
    await act(async () => editor.onChange(source));
    const button = (label: string) => [...document.querySelectorAll<HTMLButtonElement>("button")].find(b => b.textContent === label)!;
    expect([...document.querySelectorAll("button")].some(b => b.textContent?.startsWith("界栏"))).toBe(false);
    // 默认开的两个格线开关先拨回全关基线，再验证全关时也能一键打开两栏空格。
    await act(async () => button("字格开").click());
    await act(async () => button("原图字格开").click());
    await act(async () => button("仅显示空格").click());
    expect(button("仅显示空格").getAttribute("aria-pressed")).toBe("true");
    expect(button("字格关").disabled).toBe(true);
    expect(button("原图字格关").disabled).toBe(true);
    expect(container.textContent).toContain("正在识别原图空格");
    expect(container.querySelector("[data-render-blank]")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    const respond = (index: number, ok = true) => act(async () => pending[index].resolve({
      ok, json: async () => ok ? {
        ok: true, width: 1130, height: 1679,
        bands: Array.from({ length: 8 }, (_, i) => [880 - i * 120, 168, 1000 - i * 120, 1564]),
        blank_cells: [{ band: 0, col: 1, row: 22 }],
      } : { ok: false, error: "定位失败" },
    }));
    await respond(0);
    const match = (key: string) => container.querySelector(`[data-render-blank="${key}"]`)?.getAttribute("data-blank-match");
    expect(match("15:22")).toBe("yes");
    expect(match("14:23")).toBe("no");
    expect(container.querySelectorAll("[data-scan-blank]")).toHaveLength(1);
    expect(container.querySelector(".scan-cell-rule")).toBeNull();
    expect(container.querySelector(".m-lines")?.getAttribute("data-cells")).toBe("off");
    expect(container.querySelector(".m-lines")?.getAttribute("data-rules")).toBe("off");
    expect(editor.value).toBe(source);
    await act(async () => button("仅显示空格").click());
    expect(button("字格关").disabled).toBe(false);
    expect(button("原图字格关").disabled).toBe(false);
    expect(container.querySelector("[data-render-blank], [data-scan-blank]")).toBeNull();
    await act(async () => button("字格关").click());
    expect(match("15:22")).toBe("yes");
    expect(container.querySelector("[data-scan-grid]")).toBeNull();
    await act(async () => button("原图字格关").click());
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(pending).toHaveLength(1);
    expect(container.querySelectorAll("[data-scan-blank]")).toHaveLength(1);
    // 已打开的格线临时隐藏，退出后恢复；高亮和识别请求不中断。
    await act(async () => button("仅显示空格").click());
    expect(container.querySelector(".scan-cell-rule")).toBeNull();
    expect(container.querySelector(".m-lines")?.getAttribute("data-cells")).toBe("off");
    expect(match("15:22")).toBe("yes");
    expect(container.querySelectorAll("[data-scan-blank]")).toHaveLength(1);
    await act(async () => button("仅显示空格").click());
    expect(button("字格开").getAttribute("aria-pressed")).toBe("true");
    expect(button("原图字格开").getAttribute("aria-pressed")).toBe("true");
    expect(container.querySelectorAll(".scan-cell-rule")).toHaveLength(8 * 28);
    expect(container.querySelector(".m-lines")?.getAttribute("data-cells")).toBe("on");
    await act(async () => button("原图字格开").click());
    await act(async () => editor.onChange(`@1\n${"甲".repeat(23)}*\n${"乙".repeat(22)}*乙`));
    expect(match("15:22")).toBe("no"); // 原图为空，但此处已改为文字。
    expect(match("14:23")).toBeUndefined();
    expect(match("15:23")).toBe("no");
    expect(match("14:22")).toBe("no");
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(pending).toHaveLength(1);

    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="下一页"]')!.click());
    expect(container.querySelector("[data-render-blank]")).toBeNull();
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    await respond(1, false);
    expect(container.textContent).toContain("空格对照：定位失败");
    expect(container.querySelector("[data-render-blank]")).toBeNull();
    await act(async () => button("重试").click());
    await act(async () => { await vi.advanceTimersByTimeAsync(250); });
    expect(pending).toHaveLength(3);
    await act(async () => button("字格开").click());
    expect(pending[2].signal.aborted).toBe(true);
    await respond(2);
    expect(container.querySelector("[data-render-blank]")).toBeNull();
    expect(container.querySelector('[role="status"]')).toBeNull();
  });

  it("插字和插入大列后，布局、高亮与点击定位同时更新", async () => {
    expect(container.querySelector(".m-band")?.textContent).toBe("甲乙");
    const inserted = "@1\n\n#丙甲乙\n";
    await act(async () => {
      editor.onChange(inserted);
      editor.onCursor!(inserted.indexOf("甲") + 1);
    });
    expect(container.querySelector(".m-band")?.textContent).toBe("丙甲乙");
    expect(activeText()).toBe("甲");

    const restructured = "@1\n\n#𠀤$\n\n#丙甲乙\n";
    await act(async () => {
      editor.onChange(restructured);
      editor.onCursor!(restructured.indexOf("甲") + 1);
    });
    expect(container.querySelectorAll(".m-band")).toHaveLength(2);
    expect(container.querySelector(".m-band-active")?.textContent).toBe("丙甲乙");
    expect(activeText()).toBe("甲");
    await act(async () => container.querySelector<HTMLElement>(".m-band")!.click());
    expect(revealPosition).toHaveBeenLastCalledWith(restructured.indexOf("𠀤") + "𠀤".length);
  });

  it("移动光标后重复点击同一列仍执行定位；光标更新不重渲染数据集工具栏", async () => {
    const toolbarRenders = headwordRenders;
    const band = container.querySelector<HTMLElement>(".m-band")!;
    await act(async () => band.click());
    expect(activeText()).toBe("甲");
    for (let i = 0; i < 10; i++) {
      await act(async () => editor.onCursor!(sources[1].indexOf(i % 2 ? "甲" : "乙") + 1));
    }
    await act(async () => editor.onCursor!(sources[1].indexOf("乙") + 1));
    expect(activeText()).toBe("乙");
    await act(async () => band.click());
    expect(activeText()).toBe("甲");
    expect(revealPosition.mock.calls).toEqual([[sources[1].indexOf("甲") + 1], [sources[1].indexOf("甲") + 1]]);
    expect(headwordRenders).toBe(toolbarRenders);
  });

  it("切换已预取页时，预览与编辑器同时换页；返回时保留编辑缓冲", async () => {
    const edited = "@1\n\n#丙甲乙\n";
    await act(async () => editor.onChange(edited));
    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="下一页"]')!.click());
    expect(editor.value).toBe(sources[2]);
    expect(container.querySelector(".page-title")?.textContent).toBe("2");
    expect(container.querySelector(".m-band")?.textContent).toBe("戊己");
    await doubleClick(container.querySelectorAll(".m-large")[1]);
    expect(revealPosition.mock.calls).toEqual([[sources[2].indexOf("己") + 1]]);
    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="上一页"]')!.click());
    expect(editor.value).toBe(edited);
    expect(container.querySelector(".page-title")?.textContent).toBe("1");
    expect(container.querySelector(".m-band")?.textContent).toBe("丙甲乙");
  });
});
