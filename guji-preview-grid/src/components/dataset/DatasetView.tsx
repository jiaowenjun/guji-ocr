import { callPageTool } from "@/lib/page-tool";
// 数据集对照视图：扫描原图 | 刻本渲染 | .gj 编辑器 三列对照
// 清单经本地 API 读取 manifest；scripts/link-dataset.sh 只准备资源符号链接，
// 保存经 vite.config.ts 的 datasetSave dev 中间件写回 kangxi-gold/annotations/NNNN.gj。
// 渲染列宽度跟随原图列显示宽：unit = (显示宽 − 2px) / 横向字格数（pageColumns）。
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
import { ChevronLeft, ChevronRight, Database, Plus, ScanText } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import { formatDocument } from "@/components/dataset/format-document";
import { HeadwordStrip } from "@/components/dataset/HeadwordStrip";
import { resolvePageContinuation } from "@/components/dataset/headwords";
import { DatasetWorkspace } from "./DatasetWorkspace";
import { useToolbarSlot } from "@/hooks/use-toolbar-slot";
import type { DatasetConfig } from "@/datasets/config";
import { resolveDatasetIndexConfig } from "@/datasets/kangxi";

export interface PageEntry {
  page: number;
  image: string;
  gj: string;
  width: number;
  height: number;
  status?: "draft" | "first" | "final"; // 草稿 / 初校 / 精校（存于 manifest.json）
}

/** 页标签：内部值 ↔ 中文名与展示色 */
const STATUS_META: Record<PageEntry["status"] & string, { label: string; dot: string; text: string }> = {
  draft: { label: "草稿", dot: "bg-muted-foreground", text: "text-muted-foreground" },
  first: { label: "初校", dot: "bg-amber-500", text: "text-amber-600" },
  final: { label: "精校", dot: "bg-emerald-500", text: "text-emerald-600" },
};

const stem = (page: number) => String(page).padStart(4, "0");

/** 当前 manifest 页清单及配置（只读 API） */
function useDatasetIndex() {
  const [config, setConfig] = useState<DatasetConfig | null>(null);
  const [index, setIndex] = useState<PageEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  useEffect(() => {
    let alive = true;
    callPageTool<{ source?: string; config?: unknown; pages: PageEntry[] }>({ action: "dataset-index" })
      .then((data: { source?: string; config?: unknown; pages: PageEntry[] }) => {
        const selected = resolveDatasetIndexConfig(data.config, data.source);
        if (alive) {
          setConfig(selected);
          setIndex(data.pages);
          setError(null);
        }
      })
      .catch((e: unknown) =>
        alive && setError(e instanceof Error ? e.message : String(e)),
      );
    return () => {
      alive = false;
    };
  }, [reloadKey]);
  const reload = useCallback(() => setReloadKey((k) => k + 1), []);
  return { index, config, error, reload };
}

/** 各页 .gj 原文缓存；ensure() 缺失即取（含预取），失败页可重试 */
function useDatasetText() {
  const [texts, setTexts] = useState<Record<number, string>>({});
  const textsRef = useRef(texts);
  const pending = useRef(new Set<number>());
  const ensure = useCallback((pages: number[]) => {
    for (const page of pages) {
      if (page in textsRef.current || pending.current.has(page)) continue;
      pending.current.add(page);
      fetch(`/dataset/annotations/${stem(page)}.gj`)
        .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
        .then((text) => {
          textsRef.current[page] = text;
          setTexts({ ...textsRef.current });
        })
        .catch(() => {
          pending.current.delete(page);
        });
    }
  }, []);
  const put = useCallback((page: number, text: string) => {
    textsRef.current[page] = text;
    setTexts({ ...textsRef.current });
  }, []);
  return { texts, ensure, put };
}

export function DatasetView({
  editorTheme = "light",
  vimMode = false,
}: {
  editorTheme?: "light" | "dark";
  /** 编辑器 vim 模式（顶栏开关，默认关） */
  vimMode?: boolean;
}) {
  const { index, config, error, reload } = useDatasetIndex();
  const [idx, setIdx] = useState(0);
  const [edits, setEdits] = useState<Record<number, string>>({});
  const { texts, ensure, put } = useDatasetText();
  const [cells, setCells] = useState(true); // 整页字格默认开
  const [scanCells, setScanCells] = useState(true); // 原图投影字格独立开关，默认开
  const [blanksOnly, setBlanksOnly] = useState(false); // 暂时隐藏两栏格线，保留原开关状态
  const [busy, setBusy] = useState(false);
  const [ocrView, setOcrView] = useState<string | null>(null); // OCR 结果弹窗内容
  const [addBusy, setAddBusy] = useState(false); // 添加新页进行中
  const [jumpTo, setJumpTo] = useState<number | null>(null); // 添加成功后跳转
  const toolbarSlot = useToolbarSlot(); // 工具栏注入壳层插槽（见 JSX 内 portal）

  // 清单刷新后跳到新添加的页
  useEffect(() => {
    if (index && jumpTo !== null) {
      const i = index.findIndex((p) => p.page === jumpTo);
      if (i >= 0) {
        setIdx(i);
        setJumpTo(null);
      }
    }
  }, [index, jumpTo]);

  const entry = index?.[idx];
  const page = entry?.page;
  const original = page !== undefined ? texts[page] : undefined;
  const text = page !== undefined ? (edits[page] ?? original) : undefined;
  const dirty = page !== undefined && edits[page] !== undefined && edits[page] !== original;

  // 当前页 + 相邻页预取
  useEffect(() => {
    if (!index) return;
    ensure([index[idx]?.page, index[idx - 1]?.page, index[idx + 1]?.page].filter(
      (p): p is number => p !== undefined,
    ));
  }, [index, idx, ensure]);

  // 页首跨页归属：当前页用编辑缓冲实时判定；回溯读已取文本（含各页未保存编辑）
  const indexPages = useMemo(() => (index ? index.map((p) => p.page) : []), [index]);
  const knownTexts = useMemo(() => ({ ...texts, ...edits }), [texts, edits]);
  const continuation = useMemo(
    () => (page !== undefined ? resolvePageContinuation(text, page, indexPages, knownTexts) : null),
    [text, page, indexPages, knownTexts],
  );
  // 宿主候选页缺文本：补取后重算（挂起而非跳过，防选错宿主）
  useEffect(() => {
    if (continuation?.state === "pending") ensure(continuation.needPages);
  }, [continuation, ensure]);

  // ←/→、Ctrl-N/P 翻页（编辑器/表单聚焦时不劫持——Ctrl-N/P 是 CodeMirror 行移动）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!index || (e.target as HTMLElement | null)?.closest(".cm-editor, input, textarea, select")) return;
      const np = (e.ctrlKey || e.metaKey) && !e.altKey ? e.key.toLowerCase() : null;
      if (np === "n" || np === "p") e.preventDefault(); // Ctrl-P 别落进浏览器打印
      if (e.key === "ArrowRight" || np === "n") {
        if (idx < index.length - 1) setIdx(idx + 1);
      } else if (e.key === "ArrowLeft" || np === "p") {
        if (idx > 0) setIdx(idx - 1);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [index, idx]);

  const onChange = useCallback(
    (value: string) => {
      if (page === undefined) return;
      setEdits((prev) => ({ ...prev, [page]: value }));
    },
    [page],
  );

  const reset = () => {
    if (page === undefined) return;
    setEdits(({ [page]: _drop, ...rest }) => rest);
  };

  /** 添加新页：桥接 kangxi_page_tool.py（sqlite 优先，缺则增量爬取），完成后刷新清单并跳转 */
  const addPage = async (n: number) => {
    if (!Number.isInteger(n) || n < 1 || n > 7738) {
      toast.error(`页码应为 1-7738 的整数（当前：${n}）`, { duration: Infinity });
      return;
    }
    setAddBusy(true);
    const notification = toast.loading(`正在添加 @${n}…`);
    try {
      const data = await callPageTool<{
        counts?: { chars: number; unencoded: number; with_text: number };
        summaries?: string[];
      }>({ action: "add", page: n });
      const { counts, summaries } = data;
      reload();
      setJumpTo(n);
      toast.success(`已添加 @${n}`, {
        id: notification,
        description: `字头 ${counts?.chars ?? "?"} 个，含释义 ${counts?.with_text ?? "?"}，未编码 ${counts?.unencoded ?? 0}${summaries?.length ? "；" + summaries.join("；") : ""}`,
      });
    } catch (e) {
      toast.error(`添加 @${n} 失败`, {
        id: notification,
        description: e instanceof Error ? e.message : String(e),
        duration: Infinity,
      });
    } finally {
      setAddBusy(false);
    }
  };

  /** 改页标签（只写 manifest），成功后重新查询清单 */
  const setStatusOf = async (to: NonNullable<PageEntry["status"]>) => {
    if (page === undefined) return;
    try {
      await callPageTool({ action: "status", page, status: to });
      reload();
      toast.success(`@${page} 标签已改为「${STATUS_META[to].label}」`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { duration: Infinity });
    }
  };

  // useCallback：⌘S/Ctrl+S 监听可直接依赖（identity 只随 page/text 变化）。
  // content 覆写参数：格式化后立即保存新文本（setEdits 尚未落入闭包里的 text）
  const save = useCallback(async (content?: string, okMsg?: string) => {
    const body = content ?? text;
    if (page === undefined || body === undefined) return;
    setBusy(true);
    try {
      const res = await fetch("/dataset/save", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ page, content: body }),
      });
      const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
      if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
      put(page, body); // 立即可见，避免再等 fetch
      setEdits(({ [page]: _drop, ...rest }) => rest);
      toast.success(okMsg ?? `已保存 ${stem(page)}.gj`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { duration: Infinity });
    } finally {
      setBusy(false);
    }
  }, [page, text, put]);

  // ⌘S/Ctrl+S 保存：编辑器聚焦时也生效（区别于 ←/→ 翻页），并拦截浏览器“存储页面”默认行为
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.altKey || e.key.toLowerCase() !== "s") return;
      e.preventDefault();
      if (dirty && !busy) save();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save, dirty, busy]);

  /** 格式化（一键）：<U+xxxx>编号转写为实际字符、全角及行首半角空格逐个→*、行内半角空格串→*、正文后尾空白清除、
   *  ◎→〇、全角括号/速记归一、#(X 补右括号、同行重复 # 合并、行首逗号回贴前行大字、自动流式＋均式折行，
   *  保留大小字边界与显式 $ 换列。
   *  格式化即保存（2026-11-15）：缓冲与磁盘同形，省去手动「保存回数据集」；
   *  保存失败时缓冲保持未保存态，可 ⌘S 重试 */
  const formatText = () => {
    if (page === undefined || text === undefined) return;
    const { text: formatted, spaces, circles, dots, codepoints } = formatDocument(text, config?.layout);
    if (formatted === text) {
      toast.success(`@${page} 已是标准写法，无需格式化`);
      return;
    }
    setEdits((prev) => ({ ...prev, [page]: formatted }));
    const detail = [
      codepoints > 0 ? `<U+xxxx>→字符 ${codepoints} 处` : "",
      spaces > 0 ? `占位空格→* ${spaces} 处` : "",
      circles > 0 ? `◎→〇 ${circles} 处` : "",
      dots > 0 ? `•→· ${dots} 处` : "",
      "流式＋均式排版、括号归一、字头独占一行",
    ]
      .filter(Boolean)
      .join("；");
    void save(formatted, `@${page} 已格式化（${detail}）并保存 ${stem(page)}.gj`);
  };

  /** 显示 OCR 结果：弹窗展示该页 OCR markdown */
  const ocrShow = async () => {
    if (page === undefined) return;
    try {
      const data = await callPageTool<{ markdown: string | null; hint?: string }>({ action: "ocr-view", page });
      setOcrView(data.markdown ?? data.hint ?? "（无内容）");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e), { duration: Infinity });
    }
  };

  if (error || !index) {
    return (
      <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-2 p-8 text-sm">
        <Database className="size-10 opacity-30" />
        <p>{error ? "数据集访问层读取失败" : "正在读取数据集清单…"}</p>
        {error ? (
          <p className="text-xs">
            {error}；请确认本地开发服务可用后刷新页面
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 工具栏经 portal 注入 App 壳层单行工具栏左侧插槽，与其合并为一行 */}
      {toolbarSlot &&
        createPortal(
          <>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="icon-sm" aria-label="上一页" title="上一页（← 或 Ctrl-P）" disabled={idx === 0} onClick={() => setIdx(idx - 1)}>
            <ChevronLeft />
          </Button>
          <Button variant="outline" size="icon-sm" aria-label="下一页" title="下一页（→ 或 Ctrl-N）" disabled={idx === index.length - 1} onClick={() => setIdx(idx + 1)}>
            <ChevronRight />
          </Button>
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm">{entry ? `第 ${idx + 1}/${index.length} 页 · @${page}` : "页码"}</Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuLabel>{config?.title ?? "数据集"} 页清单</DropdownMenuLabel>
            <DropdownMenuSeparator />
                  {index.map((p, i) => (
                    <DropdownMenuItem key={p.page} onClick={() => setIdx(i)}>
                      <span
                        className={`inline-block size-1.5 shrink-0 rounded-full ${STATUS_META[p.status ?? "first"].dot}`}
                      />
                      @{p.page} · {STATUS_META[p.status ?? "first"].label} · {p.image}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" disabled={!entry}>
                    <span
                      className={`inline-block size-2 rounded-full ${STATUS_META[entry?.status ?? "first"].dot}`}
                    />
                    {STATUS_META[entry?.status ?? "first"].label}
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                  <DropdownMenuLabel>页标签（存 manifest.json）</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {(Object.keys(STATUS_META) as NonNullable<PageEntry["status"]>[]).map((s) => (
                    <DropdownMenuItem key={s} onClick={() => setStatusOf(s)}>
                      <span className={`inline-block size-1.5 rounded-full ${STATUS_META[s].dot}`} />
                      {STATUS_META[s].label}
                      {entry?.status === s ? " ✓" : ""}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              <Button
                size="sm"
                variant="outline"
                disabled={addBusy}
                title={`直接添加下一页 @${index.length ? index[index.length - 1].page + 1 : 313}（封顶 7738）`}
                onClick={() => {
                  // 直接添加下一页（清单最大页 +1，封顶 7738），无需二次确认
                  const maxPage = index.length ? index[index.length - 1].page : 312;
                  void addPage(Math.min(7738, maxPage + 1));
                }}
              >
                <Plus data-icon="inline-start" />
                {addBusy ? "添加中…" : "添加新页"}
              </Button>


        <Separator orientation="vertical" className="h-5" />

        <Button size="sm" variant="outline" aria-pressed={cells && !blanksOnly} disabled={blanksOnly} onClick={() => setCells((v) => !v)}
          title="显示字格并对照空格：两侧都为空时淡蓝，只有一侧为空时淡红">
          字格{cells && !blanksOnly ? "开" : "关"}
        </Button>

        <Button size="sm" variant="outline" aria-pressed={scanCells && !blanksOnly} disabled={blanksOnly} onClick={() => setScanCells((v) => !v)}>
          原图字格{scanCells && !blanksOnly ? "开" : "关"}
        </Button>

        <Button size="sm" variant={blanksOnly ? "secondary" : "outline"} aria-pressed={blanksOnly}
          onClick={() => setBlanksOnly((v) => !v)} title="两栏只高亮空格，隐藏字格线；再次点击恢复字格设置">
          仅显示空格
        </Button>

        {/* 字头段并入工具栏（原为工具栏下方独立窄条）：多页字头时随 flex-wrap 换行 */}
        <Separator orientation="vertical" className="h-5" />
        <HeadwordStrip page={page} continuation={continuation} />

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Button size="sm" variant="outline" disabled={page === undefined} onClick={ocrShow}
            title="弹窗显示该页的 PaddleOCR 识别文本">
            <ScanText data-icon="inline-start" />
            显示OCR结果
          </Button>
        </div>
          </>,
          toolbarSlot,
        )}

      <DatasetWorkspace
        entry={entry}
        config={config}
        text={text}
        originalLoaded={original !== undefined}
        dirty={dirty}
        busy={busy}
        cells={cells}
        scanCells={scanCells}
        blanksOnly={blanksOnly}
        editorTheme={editorTheme}
        vimMode={vimMode}
        onChange={onChange}
        onSave={() => void save()}
        onReset={reset}
        onFormat={formatText}
      />
          {ocrView !== null ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-6"
          onClick={() => setOcrView(null)}
        >
          <div
            className="bg-background text-foreground max-h-[80vh] w-[560px] max-w-[90vw] overflow-auto rounded-lg border p-4 text-sm shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="font-semibold">PaddleOCR 识别结果 · @{page}</span>
              <Button size="sm" variant="ghost" onClick={() => setOcrView(null)}>关闭</Button>
            </div>
            <pre className="text-muted-foreground whitespace-pre-wrap font-mono text-xs leading-6">
              {ocrView}
            </pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}
