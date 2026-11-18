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

describe("数据集预览使用当前文档快照", () => {
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
    await act(async () => document.querySelector<HTMLButtonElement>('[aria-label="上一页"]')!.click());
    expect(editor.value).toBe(edited);
    expect(container.querySelector(".page-title")?.textContent).toBe("1");
    expect(container.querySelector(".m-band")?.textContent).toBe("丙甲乙");
  });
});
