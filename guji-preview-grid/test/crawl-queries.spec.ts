// @vitest-environment jsdom
import { act, createElement, type ComponentProps } from "react";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HeadwordStrip } from "../src/components/dataset/HeadwordStrip";
import { DatasetView } from "../src/components/dataset/DatasetView";
import { KANGXI_DATASET } from "../src/datasets/kangxi";
import type { CrawlEntryRecord, CrawlPageHead } from "../src/components/dataset/crawl-entries";
import { resolvePageContinuation } from "../src/components/dataset/headwords";

// 加页集成用真实 DatasetView/字头栏，只替换与查询无关的三列编辑布局。
vi.mock("../src/components/dataset/DatasetWorkspace", () => ({
  DatasetWorkspace: ({ text, onChange }: { text?: string; onChange: (text: string) => void }) =>
    createElement("div", null,
      createElement("pre", null, text),
      createElement("button", { onClick: () => onChange("@366\n\n#云\n未保存编辑") }, "测试编辑")),
}));

let root: Root;
let container: HTMLDivElement;
let requests: Array<{
  body: { action: string; page?: number; codepoint?: number };
  signal: AbortSignal;
  resolve: (response: unknown) => void;
}>;

const head = (char = "互"): CrawlPageHead => ({
  ord: 0, char, codepoint: char.codePointAt(0)!, k_code: null, svg: `${char}.svg`,
});
const entry = (text: string): CrawlEntryRecord => ({
  head: "互", guwen: null, juan: null, unicode: "U+4E92", radical: "二",
  radical_strokes: 2, extra_strokes: 2, total_strokes: 4, pinyin: [], zhuyin: [],
  cangjie: null, unihan: null, tongwen_edition: null, wuying_edition: null,
  text_paragraphs: [text], pua_other: [],
});
const render = (page?: number, continuation?: ComponentProps<typeof HeadwordStrip>["continuation"]) =>
  act(async () => root.render(createElement(HeadwordStrip, { page, continuation })));
const reply = (index: number, payload: object, ok = true) => act(async () => {
  requests[index].resolve({ ok, status: ok ? 200 : 400, json: async () => payload });
});
const click = (selector: string) => act(async () => {
  const button = container.querySelector<HTMLButtonElement>(selector);
  expect(button, selector).not.toBeNull();
  button!.click();
});

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  Object.defineProperty(document, "fonts", {
    configurable: true, value: { load: async () => [], check: () => true },
  });
  requests = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init: RequestInit) => {
    expect(url).toBe("/dataset/page-tool");
    expect(init.method).toBe("POST");
    expect(init.cache).toBe("no-store");
    return new Promise((resolve) => requests.push({
      body: JSON.parse(String(init.body)), signal: init.signal!, resolve,
    }));
  }));
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

describe("字头栏按需查询当前爬取库", () => {
  it("371 页真实稿件在新字头前显示 370 页些条续文，点击查询宿主全文", async () => {
    const read = (page: number) => readFileSync(resolve(dirname(fileURLToPath(import.meta.url)),
      "../../kangxi-gold/annotations", `${String(page).padStart(4, "0")}.gj`), "utf8");
    const continuation = resolvePageContinuation(read(371), 371, [370, 371], { 370: read(370) });
    expect(continuation).toMatchObject({ state: "host", fromPage: 370, cluster: { head: "些" } });
    await render(371, continuation);
    await reply(0, { ok: true, heads: [head("𠄨"), head("亝"), head("亞")] });
    const host = container.querySelector<HTMLButtonElement>('button[title*="@370「些」"]');
    expect(host?.textContent).toContain("@370 ↩些");
    expect(container.textContent).toContain("爬取 3");
    await click('button[title*="@370「些」"]');
    expect(requests[1].body).toEqual({ action: "crawl-entry", codepoint: "些".codePointAt(0) });
    await reply(1, { ok: true, entry: { ...entry("寫耶切……皆蠻族。"), head: "些" } });
    expect(container.textContent).toContain("寫耶切……皆蠻族。");
  });

  it("缺字映射失败可重试，使用 API 返回的本地 URL", async () => {
    Object.defineProperty(document, "fonts", {
      configurable: true, value: { load: async () => [], check: () => false },
    });
    await render(367);
    await reply(0, { ok: true, heads: [head()] });
    expect(requests[1].body).toEqual({ action: "crawl-glyphs", codepoints: [0x4e92] });
    await reply(1, { ok: false, error: "temporary" }, false);
    await click('button[title="temporary"]');
    await reply(2, { ok: true, glyphs: { 互: "/dataset/head-svg/current.svg" } });
    expect(container.querySelector('img[src="/dataset/head-svg/current.svg"]')).not.toBeNull();
  });
  it("添加新页后直接查到新字头，返回旧页仍保留未保存编辑", async () => {
    let added = false;
    const queries: object[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url === "/dataset/page-tool" && JSON.parse(String(init?.body)).action === "dataset-index") return {
        ok: true, json: async () => ({ ok: true, config: KANGXI_DATASET, pages: (added ? [366, 367] : [366]).map((page) => ({
          page, image: `${page}.jpg`, gj: `${page}.gj`, width: 1130, height: 1679,
        })) }),
      };
      if (url === "/dataset/annotations/0366.gj" || url === "/dataset/annotations/0367.gj") return {
        ok: true, text: async () => url.includes("0366") ? "@366\n\n#云\n" : "@367\n\n#互\n",
      };
      expect(url).toBe("/dataset/page-tool");
      const body = JSON.parse(String(init?.body));
      queries.push(body);
      if (body.action === "add") {
        added = true;
        return { ok: true, json: async () => ({ ok: true, page: 367, counts: { chars: 1, with_text: 1, unencoded: 0 } }) };
      }
      expect(body.action).toBe("crawl-heads");
      return { ok: true, json: async () => ({ ok: true, heads: [head(body.page === 366 ? "云" : "互")] }) };
    }));
    await act(async () => root.unmount());
    const toolbar = document.createElement("div");
    toolbar.id = "app-toolbar-slot";
    // Portal 目标放在 root 之外，防止 React 挂载时清除它。
    const workspace = document.createElement("div");
    container.append(toolbar, workspace);
    root = createRoot(workspace);
    await act(async () => root.render(createElement(DatasetView)));
    const clickText = (text: string) => act(async () => {
      [...container.querySelectorAll("button")].find((b) => b.textContent === text)!.click();
    });
    await clickText("测试编辑");
    await clickText("添加新页");
    expect(container.querySelector('button[title="爬取字头详情：互"]')).not.toBeNull();
    expect(queries).toContainEqual({ action: "add", page: 367 });
    expect(queries).toContainEqual({ action: "crawl-heads", page: 367 });
    await click('button[aria-label="上一页"]');
    expect(container.querySelector("pre")?.textContent).toContain("未保存编辑");
  });

  it("从未选页到新页只查该页，重渲染不重复请求，点击才查单字详情", async () => {
    await render();
    expect(requests).toHaveLength(0);
    await render(367);
    expect(container.textContent).toContain("字头加载中");
    expect(container.textContent).not.toContain("爬取 0");
    expect(requests[0].body).toEqual({ action: "crawl-heads", page: 367 });
    await reply(0, { ok: true, heads: [head()] });
    expect(container.textContent).toContain("爬取 1");
    await render(367);
    expect(requests).toHaveLength(1);
    await click('button[title="爬取字头详情：互"]');
    expect(requests[1].body).toEqual({ action: "crawl-entry", codepoint: 0x4E92 });
    expect(container.textContent).toContain("加载中");
    await reply(1, { ok: true, entry: entry("互的完整释文") });
    expect(container.textContent).toContain("互的完整释文");
  });

  it("零字头、未采集和查询失败分别展示；失败可重试", async () => {
    await render(332);
    await reply(0, { ok: true, heads: [] });
    expect(container.textContent).toBe("爬取 0");
    await render(368);
    await reply(1, { ok: true, heads: null });
    expect(container.textContent).toContain("该页字头尚未采集");
    expect(container.textContent).not.toContain("爬取 0");
    await click("button");
    await reply(2, { ok: false, error: "database unavailable" }, false);
    expect(container.textContent).toContain("字头查询失败");
    expect(container.textContent).not.toContain("爬取 0");
    await click("button");
    expect(container.textContent).toContain("字头加载中");
    await reply(3, { ok: true, heads: [head()] });
    expect(container.textContent).toContain("爬取 1");
  });

  it("快速切页时取消旧请求，即使旧响应晚到也不会覆盖新页", async () => {
    await render(366);
    await render(367);
    expect(requests[0].signal.aborted).toBe(true);
    await reply(1, { ok: true, heads: [head()] });
    await reply(0, { ok: true, heads: [head("云"), head("丁")] });
    expect(container.textContent).toContain("爬取 1");
    expect(container.querySelector('button[title="爬取字头详情：互"]')).not.toBeNull();
    expect(container.querySelector('button[title="爬取字头详情：云"]')).toBeNull();
    await render(366);
    await render(367);
    expect(container.textContent).toContain("字头加载中");
    expect(container.querySelector('button[title="爬取字头详情：互"]')).toBeNull();
    await reply(3, { ok: true, heads: [head()] });
    expect(container.textContent).toContain("爬取 1");
  });

  it("重开弹窗读取更新词条，关闭前未完成的查询不会污染新弹窗", async () => {
    await render(367);
    await reply(0, { ok: true, heads: [head()] });
    await click('button[title="爬取字头详情：互"]');
    await click(".fixed button");
    expect(requests[1].signal.aborted).toBe(true);
    await click('button[title="爬取字头详情：互"]');
    await reply(2, { ok: true, entry: entry("最新词条") });
    await reply(1, { ok: true, entry: entry("过期词条") });
    expect(container.textContent).toContain("最新词条");
    expect(container.textContent).not.toContain("过期词条");
    expect(requests.filter((r) => r.body.action === "crawl-heads")).toHaveLength(1);
  });

  it("补充平面字按完整码位查询，未收录与详情失败可以区分", async () => {
    await render(312);
    await reply(0, { ok: true, heads: [head("𠀀")] });
    await click('button[title="爬取字头详情：𠀀"]');
    expect(requests[1].body.codepoint).toBe(0x20000);
    await reply(1, { ok: false, error: "read failure" }, false);
    expect(container.textContent).toContain("词条查询失败");
    await act(async () => {
      [...container.querySelectorAll("button")].find((b) => b.textContent === "重试")!.click();
    });
    await reply(2, { ok: true, entry: null });
    expect(container.textContent).toContain("爬取库未收录此字头");
    expect(container.textContent).not.toContain("词条查询失败");
  });

  it("未编码项保留字形，前页等待态无需虚构延续行数", async () => {
    await render(367, { state: "pending", needPages: [366] });
    await reply(0, { ok: true, heads: [{ ...head(), char: null, codepoint: null, k_code: "K123" }] });
    expect(container.textContent).toContain("前页取文中");
    expect(container.textContent).toContain("爬取 1");
    expect(container.querySelector('img[src="/dataset/head-svg/%E4%BA%92.svg"]')).not.toBeNull();
    expect(container.querySelector('button[title^="爬取字头详情"]')).toBeNull();
  });
});
