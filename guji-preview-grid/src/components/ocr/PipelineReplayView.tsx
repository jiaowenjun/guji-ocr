import { callPageTool as callTool } from "@/lib/page-tool";
// 添加新页流程演示视图：以初校页为样例集，只读重放 add 管线逐步骤展示中间结果，
// 并与人工初校 .gj 对照（字符流/行界带界 F1/漏多折/分歧块）——观察、调试、找错。
// 数据源全走 /dataset/page-tool（replay-pages 样例集 / pipeline-replay 单页全量），
// 后端零写盘（不爬取、不落 .gj、不触发预取）；与 OcrPrefetchView 共用 callTool 模式。
import { useCallback, useEffect, useState } from "react";
import { CircleDashed, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";

type ReplayPage = { page: number; bands_n: number; lines_n: number };

type Stage = { name: string; label: string; bands: string[][]; note: string };

type Replay = {
  page: number;
  data: { heads: string[]; unencoded_n: number; missing_entries: string[] };
  continuation: {
    info: {
      prev_page: number;
      head: string | null;
      paragraphs: number;
      skipped: string | null;
      host_page?: number;
      fully_included?: boolean;
    };
    rest_paragraphs: string[];
  };
  trim_cont: { note: string; kept: string[] };
  draft: {
    counts: Record<string, number>;
    stages: Stage[];
  };
  compare: {
    ok_stream: boolean;
    lf1: number;
    bf1: number;
    auto: { bands: number; lines: number; chars: number };
    gold: { bands: number; lines: number; chars: number };
    missing_line_breaks: number[];
    extra_line_breaks: number[];
    missing_band_breaks: number[];
    extra_band_breaks: number[];
    first_diff: { offset: number; auto_ctx: string; gold_ctx: string } | null;
    diff_blocks: { tag: string; auto: string; gold: string; ctx: string }[];
    diff_blocks_total: number;
  };
  gold: string;
};

const STEPS = [
  { id: "data", label: "① 数据" },
  { id: "cont", label: "② 前页续入" },
  { id: "trim", label: "③ 续文裁剪" },
  { id: "draft", label: "④ 草稿构建" },
  { id: "compare", label: "⑤ 对照找错" },
  { id: "gold", label: "⑥ 金标原文" },
] as const;

const SK_STEPS = [
  { id: "sk-draft", label: "① OCR 底稿" },
  { id: "sk-cols", label: "② 分列分段" },
  { id: "sk-fix", label: "③ 蓝本纠错" },
  { id: "sk-result", label: "④ 终稿对照" },
] as const;

type Compare = Replay["compare"];

type SkeletonCol = {
  index: number;
  norm_len: number;
  groups_n: number;
  markdown: string;
  empty: boolean;
  gold_band_chars: number | null;
  gold_band_lines: number | null;
};

type Skeleton = {
  page: number;
  draft_ocr: { markdown: string; norm_len: number; groups_n: number };
  regrouped_ocr: {
    markdown: string;
    seg_lines: number[];
    gold_band_lines: number[];
    stray: number;
  };
  columns: SkeletonCol[];
  blueprint: { norm_len: number; source: string };
  fix: {
    replace_chars: number;
    ocr_only_chars: number;
    blueprint_only_chars: number;
    diff_blocks: { tag: string; blueprint: string; ocr: string }[];
    diff_blocks_total: number;
  };
  result: { bands: string[][]; residual_chars: number };
  compare: Compare;
  verdict: { empty_cols: number; cols_n: number; gold_bands_n: number };
};

const COUNT_LABELS: Record<string, string> = {
  chars: "字头",
  with_text: "含释义",
  unencoded: "未编码",
  guwen_merged: "古文归并",
  companions: "伴随字形",
  skipped_dup: "跳过延续字头",
};

function SectionCard({
  id,
  title,
  meta,
  children,
}: {
  id: string;
  title: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={`step-${id}`} className="scroll-mt-2 border-b px-3 py-2.5">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
        <h2 className="text-xs font-semibold">{title}</h2>
        {meta ? <span className="text-muted-foreground text-[11px]">{meta}</span> : null}
      </div>
      {children}
    </section>
  );
}

function BandList({ bands }: { bands: string[][] }) {
  return (
    <div className="grid grid-cols-2 gap-1.5 xl:grid-cols-3">
      {bands.map((band, i) => (
        <div key={i} className="rounded border p-1.5">
          <div className="text-muted-foreground mb-1 text-[10px]">
            带 {i + 1} · {band.length} 行
          </div>
          {band.map((line, j) => (
            <div key={j} className="font-mono text-[11px] leading-5 break-all">
              <span className="text-muted-foreground/60 mr-1 inline-block w-4 text-right tabular-nums">
                {j + 1}
              </span>
              {line}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function PipelineReplayView() {
  const [pages, setPages] = useState<ReplayPage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  // 重放结果带页码缓存（渲染时按选中页取用）：切换页码无需在 effect 里
  // 同步清空旧值，避免 set-state-in-effect 级联渲染
  const [replay, setReplay] = useState<{ page: number; data: Replay | null; error: string | null } | null>(
    null,
  );
  const [skeleton, setSkeleton] = useState<{ page: number; data: Skeleton | null; error: string | null } | null>(
    null,
  );
  const [mode, setMode] = useState<"pipeline" | "skeleton">("pipeline");
  const [stageIdx, setStageIdx] = useState(3); // 默认终态（重组后）

  const reload = useCallback(() => setReloadKey((k) => k + 1), []);

  // 样例集清单；就绪后默认选最大页（最新初校）
  useEffect(() => {
    let alive = true;
    callTool<{ pages: ReplayPage[] }>({ action: "replay-pages" })
      .then((d) => {
        if (!alive) return;
        setPages(d.pages);
        setError(null);
        setSelected((cur) => {
          if (cur !== null && d.pages.some((p) => p.page === cur)) return cur;
          return d.pages.length ? d.pages[d.pages.length - 1].page : null;
        });
      })
      .catch((e: unknown) => alive && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      alive = false;
    };
  }, [reloadKey]);

  // 选中页全量重放（结果带页码；按模式取生产管线或 OCR 骨架实验）
  useEffect(() => {
    if (selected === null) return;
    let alive = true;
    const setter = mode === "pipeline" ? setReplay : setSkeleton;
    callTool<Replay | Skeleton>({ action: mode === "pipeline" ? "pipeline-replay" : "ocr-skeleton-replay", page: selected })
      .then((d) =>
        alive &&
        setter({ page: selected, data: d as never, error: null }),
      )
      .catch((e: unknown) =>
        alive && setter({ page: selected, data: null, error: e instanceof Error ? e.message : String(e) }),
      );
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reloadKey 让「刷新」按钮也重取重放
  }, [selected, mode, reloadKey]);

  if (error || (!pages && !error)) {
    return (
      <div className="text-muted-foreground flex flex-1 flex-col items-center justify-center gap-2 p-8 text-sm">
        <CircleDashed className="size-10 opacity-30" />
        <p>{error ? "page-tool 桥接失败" : "正在读取样例集…"}</p>
        {error ? <p className="text-xs">{error}</p> : null}
      </div>
    );
  }

  // 深查结果按选中页+模式取用（页码不匹配 = 加载中）
  const cur = mode === "pipeline"
    ? (replay?.page === selected ? replay : null)
    : (skeleton?.page === selected ? skeleton : null);
  const curReplay = mode === "pipeline" ? ((cur?.data as Replay | null) ?? null) : null;
  const curSkeleton = mode === "skeleton" ? ((cur?.data as Skeleton | null) ?? null) : null;
  const cont = curReplay?.continuation;
  const cmp = (curReplay ?? curSkeleton)?.compare;
  const stage = curReplay?.draft.stages[
    Math.min(stageIdx, (curReplay?.draft.stages.length ?? 1) - 1)
  ];

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左：初校页样例集 + 流程模式切换 */}
      <div className="w-52 shrink-0 border-r">
        <div className="text-muted-foreground border-b px-3 py-1.5 text-xs">
          初校样例集 · {pages!.length} 页
        </div>
        <div className="flex items-center gap-1 border-b p-1">
          <Button
            size="sm"
            variant={mode === "pipeline" ? "default" : "ghost"}
            className="h-6 flex-1 px-1 text-[11px]"
            onClick={() => setMode("pipeline")}
          >
            生产管线
          </Button>
          <Button
            size="sm"
            variant={mode === "skeleton" ? "default" : "ghost"}
            className="h-6 flex-1 px-1 text-[11px]"
            onClick={() => setMode("skeleton")}
          >
            OCR 骨架实验
          </Button>
        </div>
        <ScrollArea className="h-[calc(100%-65px)]">
          {pages!.map((p) => (
            <button
              key={p.page}
              className={`flex w-full items-center gap-2 px-3 py-1 text-left text-xs ${
                p.page === selected ? "bg-accent" : "hover:bg-accent/50"
              }`}
              onClick={() => setSelected(p.page)}
            >
              <span className="tabular-nums">@{p.page}</span>
              <span className="text-muted-foreground ml-auto tabular-nums">
                {p.bands_n}带/{p.lines_n}行
              </span>
            </button>
          ))}
        </ScrollArea>
      </div>

      {/* 右：逐步骤中间结果（垂直滚动，全部展开） */}
      <ScrollArea className="min-w-0 flex-1">
        {!(curReplay ?? curSkeleton) && !cur?.error ? (
          <div className="text-muted-foreground flex h-40 items-center justify-center gap-2 text-sm">
            <RefreshCw className="size-4 animate-spin" /> 重放 @{selected} 中…
          </div>
        ) : null}
        {cur?.error ? (
          <div className="text-destructive p-3 text-sm">重放失败：{cur.error}</div>
        ) : null}

        {curSkeleton ? (
          <div>
            <div className="bg-background/60 sticky top-0 z-10 flex flex-wrap items-center gap-1 border-b px-3 py-1.5 text-xs backdrop-blur">
              <span className="mr-1 font-semibold tabular-nums">@{curSkeleton.page}</span>
              {SK_STEPS.map((s) => (
                <a key={s.id} href={`#step-${s.id}`} className="hover:bg-accent rounded px-1.5 py-0.5">
                  {s.label}
                </a>
              ))}
              <Button size="sm" variant="ghost" className="ml-auto h-6 px-2" onClick={reload}>
                刷新
              </Button>
            </div>

            <SectionCard
              id="sk-draft"
              title="① OCR 底稿（整页）"
              meta="page_ocr：文字骨架来源，含 ~7% 错字（vs 金标实测）"
            >
              <div className="mb-2 flex flex-wrap gap-3 text-xs">
                <span>归一字符 <b className="tabular-nums">{curSkeleton.draft_ocr.norm_len}</b></span>
                <span className="text-muted-foreground">行组 {curSkeleton.draft_ocr.groups_n}</span>
                <span className="text-muted-foreground">
                  蓝本（库文流）{curSkeleton.blueprint.norm_len} 字
                </span>
              </div>
              {/* 原图 ↔ 整页 OCR ↔ 分列 OCR 三列对照（图按视口高度等比缩放，整页一屏可见） */}
              <ResizablePanelGroup orientation="horizontal" className="min-h-0 rounded border">
                <ResizablePanel defaultSize={30} minSize={15}>
                  <ScrollArea className="h-[72vh]">
                    <img
                      src={`/dataset/images/${String(curSkeleton.page).padStart(4, "0")}.jpg`}
                      alt={`@${curSkeleton.page} 扫描图`}
                      className="mx-auto max-h-[72vh] w-auto max-w-full object-contain"
                      onError={(e) => {
                        e.currentTarget.style.display = "none";
                        e.currentTarget.after(
                          Object.assign(document.createElement("p"), {
                            className: "text-muted-foreground p-3 text-xs",
                            textContent: "扫描图不可访问（软链或外置盘未挂载）",
                          }),
                        );
                      }}
                    />
                  </ScrollArea>
                </ResizablePanel>
                <ResizableHandle />
                <ResizablePanel defaultSize={24} minSize={12}>
                  <ScrollArea className="h-[72vh]">
                    <div className="text-muted-foreground px-2 py-1 text-[10px]">整页 OCR</div>
                    <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap p-2">
                      {curSkeleton.draft_ocr.markdown}
                    </pre>
                  </ScrollArea>
                </ResizablePanel>
                <ResizableHandle />
                <ResizablePanel defaultSize={32} minSize={15}>
                  <ScrollArea className="h-[72vh]">
                    <div className="text-muted-foreground px-2 py-1 text-[10px]">
                      分列 OCR（列 1 = 最右，阅读序）
                    </div>
                    {curSkeleton.columns.map((c) => (
                      <div key={c.index} className="border-t px-2 py-1">
                        <div
                          className={`text-[10px] ${c.empty ? "text-destructive" : "text-muted-foreground"}`}
                        >
                          列 {c.index} · {c.norm_len} 字 · 行组 {c.groups_n}
                          {c.empty ? "（空列漏识）" : ""}
                        </div>
                        <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap">
                          {c.markdown ? c.markdown.replace(/\n{2,}/g, "\n") : "∅"}
                        </pre>
                      </div>
                    ))}
                  </ScrollArea>
                </ResizablePanel>
                <ResizableHandle />
                <ResizablePanel defaultSize={24} minSize={15}>
                  <ScrollArea className="h-[72vh]">
                    <div className="text-muted-foreground px-2 py-1 text-[10px]">
                      归列重排（整页行组×分列证据：同列聚合、列间空行；无主 {curSkeleton.regrouped_ocr.stray}）
                    </div>
                    <div className="text-muted-foreground px-2 pb-1 font-mono text-[10px]">
                      段行数 {curSkeleton.regrouped_ocr.seg_lines.join(",")} | 金标{" "}
                      {curSkeleton.regrouped_ocr.gold_band_lines.join(",")}
                    </div>
                    <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap p-2">
                      {curSkeleton.regrouped_ocr.markdown}
                    </pre>
                  </ScrollArea>
                </ResizablePanel>
              </ResizablePanelGroup>
            </SectionCard>

            <SectionCard
              id="sk-cols"
              title="② 分列分段（列界 = 带界）"
              meta={`page_column_ocr：${curSkeleton.verdict.cols_n} 列，空列 ${curSkeleton.verdict.empty_cols}；金标 ${curSkeleton.verdict.gold_bands_n} 带`}
            >
              <div className="space-y-1">
                {curSkeleton.columns.map((c) => (
                  <div key={c.index} className="flex flex-wrap items-baseline gap-2 rounded border p-1.5 text-xs">
                    <span className="w-14 shrink-0 font-semibold">列 {c.index}</span>
                    {c.empty ? (
                      <span className="text-destructive">空列（整列漏识）</span>
                    ) : (
                      <span className="tabular-nums">{c.norm_len} 字</span>
                    )}
                    {c.gold_band_chars !== null ? (
                      <span
                        className={
                          c.gold_band_chars === 0 ||
                          Math.abs(c.norm_len - c.gold_band_chars) <= Math.max(4, c.gold_band_chars * 0.15)
                            ? "text-emerald-600"
                            : "text-amber-600"
                        }
                        title="列字符量 vs 金标对应带字符量"
                      >
                        vs 金标带 {c.gold_band_chars} 字/{c.gold_band_lines} 行
                      </span>
                    ) : null}
                    <span className="text-muted-foreground">行组 {c.groups_n}</span>
                    {c.markdown ? (
                      <pre className="text-muted-foreground w-full font-mono text-[10px] leading-4 whitespace-pre-wrap">
                        {c.markdown.slice(0, 160)}
                        {c.markdown.length > 160 ? "…" : ""}
                      </pre>
                    ) : null}
                  </div>
                ))}
              </div>
            </SectionCard>

            <SectionCard
              id="sk-fix"
              title="③ 蓝本纠错（库文对齐替换）"
              meta="SequenceMatcher(蓝本, 底稿)：replace=错字改库文 / insert=伪读删去 / delete=漏识补入"
            >
              <div className="mb-2 flex flex-wrap gap-3 text-xs">
                <span>替换 <b className="tabular-nums">{curSkeleton.fix.replace_chars}</b> 字</span>
                <span className="text-amber-600">OCR 伪读 {curSkeleton.fix.ocr_only_chars} 字（删去）</span>
                <span className="text-destructive">OCR 漏识 {curSkeleton.fix.blueprint_only_chars} 字（补入）</span>
                <span className="text-muted-foreground">分歧块 {curSkeleton.fix.diff_blocks_total} 处</span>
              </div>
              <div className="space-y-1">
                {curSkeleton.fix.diff_blocks.map((b, i) => (
                  <div key={i} className="rounded border p-1.5 text-[11px]">
                    <span className="text-muted-foreground">[{b.tag}]</span>{" "}
                    <span className="font-mono break-all">OCR「{b.ocr || "∅"}」→ 蓝本「{b.blueprint || "∅"}」</span>
                  </div>
                ))}
              </div>
            </SectionCard>

            <SectionCard
              id="sk-result"
              title="④ 终稿对照（切段终稿 vs 金标）"
              meta={`蓝文字符按列字符量切段；残余 ${curSkeleton.result.residual_chars} 字；折行证据缺位（分列行组真值率仅 32%）`}
            >
              <div className="mb-2 flex flex-wrap gap-3 text-xs">
                <span className={cmp?.ok_stream ? "text-emerald-600" : "text-amber-600"}>
                  字符流 {cmp?.ok_stream ? "一致" : "有分歧"}
                </span>
                <span>行界 F1 {cmp?.lf1}</span>
                <span>带界 F1 {cmp?.bf1}</span>
                {cmp ? (
                  <span className="text-muted-foreground">
                    终稿 {cmp.auto.bands}带/{cmp.auto.lines}行/{cmp.auto.chars}字 · 金标{" "}
                    {cmp.gold.bands}带/{cmp.gold.lines}行/{cmp.gold.chars}字
                  </span>
                ) : null}
              </div>
              <BandList bands={curSkeleton.result.bands} />
            </SectionCard>
          </div>
        ) : null}

        {curReplay ? (
          <div>
            {/* 锚点导航 */}
            <div className="bg-background/60 sticky top-0 z-10 flex flex-wrap items-center gap-1 border-b px-3 py-1.5 text-xs backdrop-blur">
              <span className="mr-1 font-semibold tabular-nums">@{curReplay.page}</span>
              {STEPS.map((s) => (
                <a
                  key={s.id}
                  href={`#step-${s.id}`}
                  className="hover:bg-accent rounded px-1.5 py-0.5"
                >
                  {s.label}
                </a>
              ))}
              <Button size="sm" variant="ghost" className="ml-auto h-6 px-2" onClick={reload}>
                刷新
              </Button>
            </div>

            <SectionCard id="data" title="① 数据现状" meta="page_heads + entries（只读，不抓取）">
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <span className="font-mono text-sm">{curReplay.data.heads.join(" ") || "（无字头·纯延续页）"}</span>
                <span className="text-muted-foreground">未编码字形 {curReplay.data.unencoded_n}</span>
                {curReplay.data.missing_entries.length ? (
                  <span className="text-destructive">
                    缺详情：{curReplay.data.missing_entries.join("")}
                  </span>
                ) : (
                  <span className="text-emerald-600">字头详情齐全</span>
                )}
              </div>
            </SectionCard>

            <SectionCard
              id="cont"
              title="② 前页续入"
              meta={`continuation_from_prev（前页 .gj = 人工初校版）`}
            >
              {cont?.info.skipped ? (
                <p className="text-amber-600 text-xs">{cont.info.skipped}</p>
              ) : (
                <p className="text-xs">
                  宿主 @{cont?.info.host_page} 字头「{cont?.info.head}」→ 余{" "}
                  {cont?.info.paragraphs} 段
                </p>
              )}
              {cont?.rest_paragraphs.length ? (
                <div className="mt-1.5 space-y-1">
                  {cont.rest_paragraphs.map((p, i) => (
                    <div key={i} className="rounded border p-1.5">
                      <div className="text-muted-foreground mb-0.5 text-[10px]">余段 {i + 1}</div>
                      <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap">{p}</pre>
                    </div>
                  ))}
                </div>
              ) : null}
            </SectionCard>

            <SectionCard id="trim" title="③ 续文 OCR 裁剪" meta="ocr_trim_continuation">
              <p className="text-xs">{curReplay.trim_cont.note}</p>
              {curReplay.trim_cont.kept.map((p, i) => (
                <pre key={i} className="mt-1 rounded border p-1.5 font-mono text-[11px] leading-5 whitespace-pre-wrap">
                  裁后段 {i + 1}：{p}
                </pre>
              ))}
            </SectionCard>

            <SectionCard
              id="draft"
              title="④ 草稿构建"
              meta={Object.entries(curReplay.draft.counts)
                .filter(([k]) => COUNT_LABELS[k])
                .map(([k, v]) => `${COUNT_LABELS[k]} ${v}`)
                .join(" · ")}
            >
              <div className="mb-2 flex flex-wrap items-center gap-1">
                {curReplay.draft.stages.map((s, i) => (
                  <Button
                    key={s.name}
                    size="sm"
                    variant={i === stageIdx ? "default" : "outline"}
                    className="h-6 px-2 text-xs"
                    onClick={() => setStageIdx(i)}
                  >
                    {s.label}
                  </Button>
                ))}
              </div>
              {stage ? (
                <>
                  <p className="text-muted-foreground mb-1.5 text-[11px]">{stage.note}</p>
                  <BandList bands={stage.bands} />
                </>
              ) : null}
            </SectionCard>

            <SectionCard
              id="compare"
              title="⑤ 对照找错"
              meta="自动重组后 vs 人工初校（指标口径同 eval_pipeline_replay）"
            >
              {cmp ? (
                <>
                  <div className="mb-2 flex flex-wrap items-center gap-3 text-xs">
                    <span className={cmp.ok_stream ? "text-emerald-600" : "text-amber-600"}>
                      字符流 {cmp.ok_stream ? "一致" : "有分歧"}
                    </span>
                    <span>行界 F1 {cmp.lf1}</span>
                    <span>带界 F1 {cmp.bf1}</span>
                    <span className="text-muted-foreground">
                      自动 {cmp.auto.bands}带/{cmp.auto.lines}行/{cmp.auto.chars}字 · 金标{" "}
                      {cmp.gold.bands}带/{cmp.gold.lines}行/{cmp.gold.chars}字
                    </span>
                    <span className="text-muted-foreground">
                      漏折 {cmp.missing_line_breaks.length} · 多折 {cmp.extra_line_breaks.length}
                      {" · "}漏带 {cmp.missing_band_breaks.length} · 多带{" "}
                      {cmp.extra_band_breaks.length}
                    </span>
                  </div>
                  {cmp.diff_blocks.length ? (
                    <div className="space-y-1">
                      <p className="text-muted-foreground text-[11px]">
                        分歧块 {cmp.diff_blocks_total} 处（对齐后；金标含人工校订/标题/注释，与库内重建天然有差）
                      </p>
                      {cmp.diff_blocks.map((b, i) => (
                        <div key={i} className="flex flex-col gap-0.5 rounded border p-1.5 text-[11px]">
                          <span className="text-muted-foreground">
                            [{b.tag}] {b.ctx}
                          </span>
                          {b.auto ? (
                            <span className="text-destructive font-mono break-all">自动：{b.auto}</span>
                          ) : null}
                          {b.gold ? (
                            <span className="text-emerald-700 dark:text-emerald-400 font-mono break-all">
                              金标：{b.gold}
                            </span>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="text-emerald-600 text-xs">无分歧块——字符流逐字一致</p>
                  )}
                </>
              ) : null}
            </SectionCard>

            <SectionCard id="gold" title="⑥ 金标原文" meta="人工初校 .gj（终态对照）">
              <pre className="font-mono text-[11px] leading-5 whitespace-pre-wrap">{curReplay.gold}</pre>
            </SectionCard>
          </div>
        ) : null}
      </ScrollArea>
    </div>
  );
}
