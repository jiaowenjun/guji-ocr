// @vitest-environment jsdom
import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import { OcrPrefetchView } from "../src/components/ocr/OcrPrefetchView";

vi.mock("../src/components/ui/resizable", () => {
  const panel = ({ children }: { children: ReactNode }) => createElement("div", null, children);
  return { ResizablePanelGroup: panel, ResizablePanel: panel, ResizableHandle: () => null };
});
vi.mock("../src/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: ReactNode }) => createElement("div", null, children),
}));

let root: Root;
let container: HTMLDivElement;
let calls: string[];
let text: string;
const click = (label: string) => act(async () => {
  const button = [...document.querySelectorAll("button")].find(b => b.textContent?.trim() === label);
  expect(button).toBeDefined();
  button!.click();
});

beforeEach(async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.useFakeTimers();
  calls = [];
  text = "缓存初文";
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    const { action } = JSON.parse(String(init.body));
    calls.push(action);
    let data;
    if (action === "ocr-pages") data = { pages: [{ page: 367, dataset_status: "first", ocr_state: "invalid" }] };
    else if (action === "prefetch-status") data = {
      page: 367, markdown: text,
      steps: Object.fromEntries(["fetch", "entries", "ocr", "svg"].map(s => [s, { ok: s !== "ocr", detail: "pending" }])),
    };
    else if (action === "prefetch-log") data = { total: 0, lines: [] };
    else if (action === "prefetch-run") {
      text = "部分成功后重读";
      data = { completed: false, steps: [{ step: "ocr", ok: false, detail: "服务暂不可用" }] };
    } else throw Error(`Unexpected action: ${action}`);
    return { ok: true, json: async () => ({ ok: true, ...data }) };
  }));
  const toolbar = document.createElement("div");
  toolbar.id = "app-toolbar-slot";
  container = document.createElement("div");
  document.body.append(toolbar, container);
  root = createRoot(container);
  await act(async () => root.render(createElement(OcrPrefetchView)));
});

afterEach(async () => {
  await act(async () => root.unmount());
  document.body.replaceChildren();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

it("打开只查询；刷新同时更新详情和日志，部分预取失败也刷新且保留步骤原因", async () => {
  expect(calls).toEqual(["ocr-pages", "prefetch-log", "prefetch-status"]);
  expect(container.textContent).toContain("缓存初文");
  text = "刷新后的正文";
  await click("刷新");
  expect(container.textContent).toContain("刷新后的正文");
  expect(calls.filter(a => a === "prefetch-log")).toHaveLength(2);
  expect(calls.filter(a => a === "prefetch-status")).toHaveLength(2);
  await click("缓存失效");
  expect(container.textContent).toContain("OCR ⚠ 残缺");
  await click("预取此页");
  expect(container.textContent).toContain("服务暂不可用");
  expect(container.textContent).toContain("部分成功后重读");
  expect(calls.filter(a => a === "prefetch-log")).toHaveLength(3);
  expect(calls.filter(a => a === "prefetch-status")).toHaveLength(3);
  expect(calls.filter(a => a === "prefetch-run")).toHaveLength(1);
});
