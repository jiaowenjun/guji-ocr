// OCR 预取调试视图：多页 OCR 结果对照浏览 + prefetch_next_page 链路可视化。
// 数据源全部走 /dataset/page-tool（dev 中间件 → tools/dataset/kangxi_page_tool.py）：
//   ocr-pages 列表浅状态 / prefetch-status 单页四步深查 / ocr-view 单页 markdown /
//   prefetch-run 手动执行链路（同步等待）/ prefetch-log 日志时间线（10s 轮询）。
// 与校对视图（DatasetView）共用状态配色；本视图只读展示 + 手动预取，不写 .gj。
import { useCallback, useEffect, useState } from "react";
import {
  CheckCircle2,
  CircleDashed,
  ListRestart,
  Play,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";

/** 与 DatasetView 的 STATUS_META 同口径（页标签三态展示色） */
const STATUS_META: Record<string, { label: string; dot: string }> = {
  draft: { label: "草稿", dot: "bg-muted-foreground" },
  first: { label: "初校", dot: "bg-amber-500" },
  final: { label: "精校", dot: "bg-emerald-500" },
};

const OCR_STATE_META: Record<string, { label: string; text: string }> = {
  valid: { label: "OCR ✓", text: "text-emerald-600" },
  stale: { label: "OCR ⚠ 失效", text: "text-amber-600" },
  none: { label: "OCR ✗", text: "text-muted-foreground" },
};

type PageRow = {
  page: number;
  dataset_status: string | null;
  has_reading: boolean;
  has_scan: boolean;
  chars_n: number;
  entries_missing_n: number;
  ocr_state: "valid" | "stale" | "none";
  ocr_fetched_at: string | null;
  ocr_chars: number;
};

type StepInfo = { ok: boolean; detail: string };

type PrefetchStatus = {
  page: number;
  steps: { fetch: StepInfo; entries: StepInfo; ocr: StepInfo; svg: StepInfo };
};

type Filter = "all" | "dataset" | "no-ocr" | "stale";

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "dataset", label: "数据集内" },
  { value: "no-ocr", label: "无 OCR" },
  { value: "stale", label: "缓存失效" },
];

const stem = (page: number) => String(page).padStart(4, "0");

/** 统一调 page-tool：非 2xx / ok:false 抛异常（消息直接进状态条） */
async function callTool<T>(body: Record<string, unknown>): Promise<T> {
  const res = await fetch("/dataset/page-tool", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as { ok?: boolean; error?: string };
  if (!res.ok || !data.ok) throw new Error(data.error ?? `HTTP ${res.status}`);
  return data as T;
}

function StepBadge({ label, step }: { label: string; step: StepInfo }) {
  const Icon = step.ok ? CheckCircle2 : XCircle;
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${step.ok ? "text-emerald-600" : "text-destructive"}`}
      title={step.detail}
    >
      <Icon className="size-3.5" />
      {label}
    </span>
  );
}

export function OcrPrefetchView() {
  const [pages, setPages] = useState<PageRow[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<number | null>(null);
  // 选中页深查结果带页码（渲染时按页取用）：切换页码无需在 effect 里同步
  // 清空旧值，避免 set-state-in-effect 级联渲染
  const [status, setStatus] = useState<{ page: number; data: PrefetchStatus } | null>(null);
  const [md, setMd] = useState<{ page: number; text: string | null; hint: string | null } | null>(
    null,
  );
  const [log, setLog] = useState<{ total: number; lines: string[] } | null>(null);
  const [runInput, setRunInput] = useState("");
  const [runBusy, setRunBusy] = useState(false);
  const [runTarget, setRunTarget] = useState<number | null>(null);
  // 选中页状态的强制刷新键：手动预取完成后 selected 不变，effect 需外部键触发重拉
  const [statusKey, setStatusKey] = useState(0);
  const [msg, setMsg] = useState<{ ok: boolean; msg: string } | null>(null);

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  // 成功反馈 6s 自动消失（同 DatasetView）；错误保留至人工处理
  useEffect(() => {
    if (!msg?.ok) return;
    const t = setTimeout(() => setMsg(null), 6000);
    return () => clearTimeout(t);
  }, [msg]);

  // 页清单 + 日志首次加载；清单就绪后默认选数据集末页（预取调试关注点）
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [list, lg] = await Promise.all([
          callTool<{ pages: PageRow[] }>({ action: "ocr-pages" }),
          callTool<{ total: number; lines: string[] }>({ action: "prefetch-log", tail: 50 }),
        ]);
        if (!alive) return;
        setPages(list.pages);
        setLog(lg);
        setLoadError(null);
        setSelected((cur) => {
          if (cur !== null && list.pages.some((p) => p.page === cur)) return cur;
          const ds = list.pages.filter((p) => p.dataset_status);
          return ds.length ? ds[ds.length - 1].page : (list.pages[0]?.page ?? null);
        });
      } catch (e) {
        if (alive) setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, [reloadKey]);

  // 选中页深查：四步状态 + OCR markdown（命中缓存零开销）
  useEffect(() => {
    if (selected === null) return;
    let alive = true;
    (async () => {
      try {
        const [st, view] = await Promise.all([
          callTool<PrefetchStatus>({ action: "prefetch-status", page: selected }),
          callTool<{ markdown: string | null; hint?: string }>({ action: "ocr-view", page: selected }),
        ]);
        if (!alive) return;
        setStatus({ page: selected, data: st });
        setMd({
          page: selected,
          text: view.markdown,
          hint: view.markdown ? null : (view.hint ?? "（无内容）"),
        });
      } catch (e) {
        if (!alive) return;
        setMd({
          page: selected,
          text: null,
          hint: e instanceof Error ? e.message : String(e),
        });
      }
    })();
    return () => {
      alive = false;
    };
  }, [selected, statusKey]);

  // 日志轮询（挂载期间 10s；手动预取完成后立即刷一次）
  useEffect(() => {
    const tick = async () => {
      try {
        setLog(await callTool<{ total: number; lines: string[] }>({ action: "prefetch-log", tail: 50 }));
      } catch {
        /* 轮询失败静默（清单加载的错误提示已覆盖桥接故障场景） */
      }
    };
    const id = setInterval(tick, 10_000);
    return () => clearInterval(id);
  }, []);

  /** 手动预取：同步执行四步链路，完成后刷新该页状态与日志（未爬页会联网爬取） */
  const runPrefetch = async (page: number) => {
    setRunBusy(true);
    setRunTarget(page);
    setMsg(null);
    try {
      const r = await callTool<{ steps: { step: string; ok: boolean; detail: string }[] }>({
        action: "prefetch-run",
        page,
      });
      const detail = r.steps.map((s) => `${s.step}${s.ok ? "✓" : "✗"} ${s.detail}`).join("；");
      setMsg({ ok: r.steps.every((s) => s.ok), msg: `@${page} 预取完成：${detail}` });
      setSelected(page);
      setStatusKey((k) => k + 1);
      reload();
      setLog(await callTool<{ total: number; lines: string[] }>({ action: "prefetch-log", tail: 50 }));
    } catch (e) {
      setMsg({ ok: false, msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setRunBusy(false);
      setRunTarget(null);
    }
  };

  const runFromInput = () => {
    const n = Number(runInput);
    if (!/^\d{1,4}$/.test(runInput) || n < 1 || n > 7738) {
      setMsg({ ok: false, msg: `页码应为 1-7738 的整数（当前输入：${runInput || "空"}）` });
      return;
    }
    setRunInput("");
    void runPrefetch(n);
  };

  if (loadError || !pages) {
    return (
      <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-2 p-8 text-sm">
        <CircleDashed className="size-10 opacity-30" />
        <p>{loadError ? "page-tool 桥接失败" : "正在读取页清单…"}</p>
        {loadError ? <p className="text-xs">{loadError}</p> : null}
      </div>
    );
  }

  const visible = pages.filter((p) => {
    if (filter === "dataset") return !!p.dataset_status;
    if (filter === "no-ocr") return p.ocr_state === "none";
    if (filter === "stale") return p.ocr_state === "stale";
    return true;
  });
  const validCount = pages.filter((p) => p.ocr_state === "valid").length;
  const entry = pages.find((p) => p.page === selected) ?? null;
  // 深查结果按选中页取用（页码不匹配 = 切换中，显示加载态）
  const curStatus = status?.page === selected ? status.data : null;
  const curMd = md?.page === selected ? md : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* 工具栏：过滤 / 汇总 / 手动预取任意页 */}
      <div className="flex flex-wrap items-center gap-2 border-b px-3 py-1.5">
        <div className="flex items-center gap-1 rounded-lg border p-0.5">
          {FILTERS.map((f) => (
            <Button
              key={f.value}
              size="sm"
              variant={filter === f.value ? "default" : "ghost"}
              className="h-6 px-2 text-xs"
              onClick={() => setFilter(f.value)}
            >
              {f.label}
            </Button>
          ))}
        </div>
        <span className="text-muted-foreground text-xs">
          {visible.length}/{pages.length} 页 · OCR 有效 {validCount}
        </span>
        <Button size="sm" variant="outline" className="ml-auto" onClick={reload}>
          <ListRestart /> 刷新
        </Button>
        <input
          className="border-input bg-background h-7 w-20 rounded-md border px-2 text-xs tabular-nums"
          placeholder="页码"
          value={runInput}
          onChange={(e) => setRunInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && runFromInput()}
        />
        <Button size="sm" disabled={runBusy} title="对任意页执行预取链路（未爬页会联网爬取）" onClick={runFromInput}>
          {runBusy ? <RefreshCw className="animate-spin" /> : <Play />} 手动预取
        </Button>
      </div>

      {msg ? (
        <div
          className={`flex items-start gap-2 border-b px-3 py-1.5 text-xs ${
            msg.ok ? "text-emerald-600" : "text-destructive"
          }`}
        >
          <span className="min-w-0 flex-1 break-all">{msg.msg}</span>
          <Button size="sm" variant="ghost" className="h-5 px-1.5" onClick={() => setMsg(null)}>
            ✕
          </Button>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        {/* 左：页清单（状态点 + OCR 三态） */}
        <div className="w-52 shrink-0 border-r">
          <ScrollArea className="h-full">
            {visible.map((p) => {
              const ocr = OCR_STATE_META[p.ocr_state];
              return (
                <button
                  key={p.page}
                  className={`flex w-full items-center gap-2 px-3 py-1 text-left text-xs ${
                    p.page === selected ? "bg-accent" : "hover:bg-accent/50"
                  }`}
                  onClick={() => setSelected(p.page)}
                >
                  <span className="tabular-nums">@{p.page}</span>
                  {p.dataset_status ? (
                    <span
                      className={`inline-block size-1.5 shrink-0 rounded-full ${STATUS_META[p.dataset_status]?.dot ?? ""}`}
                      title={STATUS_META[p.dataset_status]?.label}
                    />
                  ) : null}
                  <span className={`${ocr.text} ml-auto`}>{ocr.label}</span>
                </button>
              );
            })}
            {visible.length === 0 ? (
              <p className="text-muted-foreground p-3 text-xs">该过滤条件下无页面</p>
            ) : null}
          </ScrollArea>
        </div>

        {/* 右：预取状态卡 + 图/文对照 + 日志时间线 */}
        <ResizablePanelGroup orientation="vertical" className="min-w-0 flex-1">
          <ResizablePanel defaultSize={72} minSize={40}>
            <div className="flex h-full min-h-0 flex-col">
              {/* 预取状态卡 */}
              <div className="flex flex-wrap items-center gap-3 border-b px-3 py-1.5">
                <span className="text-xs font-semibold tabular-nums">
                  @{selected ?? "—"}
                  {entry?.dataset_status ? (
                    <span className="text-muted-foreground ml-1 font-normal">
                      （{STATUS_META[entry.dataset_status]?.label}）
                    </span>
                  ) : null}
                </span>
                {curStatus ? (
                  <>
                    <StepBadge label="爬取" step={curStatus.steps.fetch} />
                    <StepBadge label="字头详情" step={curStatus.steps.entries} />
                    <StepBadge label="OCR" step={curStatus.steps.ocr} />
                    <StepBadge label="svg" step={curStatus.steps.svg} />
                  </>
                ) : (
                  <span className="text-muted-foreground text-xs">读取状态中…</span>
                )}
                <Button
                  size="sm"
                  className="ml-auto"
                  disabled={runBusy || selected === null}
                  title="对该页执行预取链路：爬取→字头详情→OCR→svg（未爬页会联网爬取）"
                  onClick={() => selected !== null && void runPrefetch(selected)}
                >
                  {runBusy && runTarget === selected ? (
                    <RefreshCw className="animate-spin" />
                  ) : (
                    <Play />
                  )}
                  预取此页
                </Button>
              </div>
              {/* 原图 ↔ OCR markdown 对照 */}
              <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1">
                <ResizablePanel defaultSize={40} minSize={20}>
                  <ScrollArea className="h-full">
                    {entry?.has_scan || entry?.dataset_status ? (
                      <img
                        src={`/dataset/images/${stem(selected ?? 0)}.jpg`}
                        alt={`@${selected} 扫描图`}
                        className="w-full"
                        onError={(e) => {
                          e.currentTarget.style.display = "none";
                          e.currentTarget.after(
                            Object.assign(document.createElement("p"), {
                              className: "text-muted-foreground p-3 text-xs",
                              textContent: "扫描图不可访问（public/dataset/images 软链或外置盘未挂载）",
                            }),
                          );
                        }}
                      />
                    ) : (
                      <p className="text-muted-foreground p-3 text-xs">该页未爬取，无扫描图</p>
                    )}
                  </ScrollArea>
                </ResizablePanel>
                <ResizableHandle />
                <ResizablePanel defaultSize={60} minSize={20}>
                  <ScrollArea className="h-full">
                    <div className="p-3">
                      {curMd?.text != null ? (
                        <pre className="font-mono text-xs leading-6 whitespace-pre-wrap">{curMd.text}</pre>
                      ) : (
                        <p className="text-muted-foreground text-xs">
                          {curMd?.hint ?? "读取 OCR 结果…"}
                        </p>
                      )}
                    </div>
                  </ScrollArea>
                </ResizablePanel>
              </ResizablePanelGroup>
            </div>
          </ResizablePanel>
          <ResizableHandle />
          <ResizablePanel defaultSize={28} minSize={10}>
            <div className="flex h-full min-h-0 flex-col">
              <div className="text-muted-foreground border-b px-3 py-1 text-xs">
                prefetch.log 时间线（10s 轮询{log ? ` · 尾部 ${log.lines.length}/${log.total} 行` : ""}）
              </div>
              <ScrollArea className="min-h-0 flex-1">
                <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap p-3">
                  {log ? log.lines.join("\n") : "（无日志）"}
                </pre>
              </ScrollArea>
            </div>
          </ResizablePanel>
        </ResizablePanelGroup>
      </div>
    </div>
  );
}
