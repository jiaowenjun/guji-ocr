// 字头条纯逻辑：提取（HEAD_CLUSTER 口径）+ 纯延续页回溯。
// 语料事实源：kangxi-gold/annotations（@313 独占行式、@331 行内式、@332/333 纯延续）。
import { describe, expect, it } from "vitest";
import { extractHeadwordClusters, resolvePageHeadwords } from "@/components/dataset/headwords";

describe("extractHeadwordClusters", () => {
  it("独占行字头组：主字头 + 古文变体", () => {
    expect(extractHeadwordClusters("#一古文#弌\n【唐韻】於悉切")).toEqual([
      { raw: "#一古文#弌", chars: ["一", "弌"] },
    ]);
  });

  it("圈号标记（增/页位次）不是字头字符，被过滤", () => {
    expect(extractHeadwordClusters("#(三)#中古文#𠁧#𠁩")).toEqual([
      { raw: "#(三)#中古文#𠁧#𠁩", chars: ["中", "𠁧", "𠁩"] },
    ]);
    expect(extractHeadwordClusters("#(增)#𠀃\n【集韻】且古作")).toEqual([
      { raw: "#(增)#𠀃", chars: ["𠀃"] },
    ]);
    // 独立成行的纯标记（如 @316 的 #(增)）整组丢弃
    expect(extractHeadwordClusters("#(增)\n#七")).toEqual([{ raw: "#七", chars: ["七"] }]);
  });

  it("异体并列、跨行古文前缀、注音冒号", () => {
    expect(extractHeadwordClusters("#丅、#𠄟")[0].chars).toEqual(["丅", "𠄟"]);
    expect(extractHeadwordClusters("古文：#㘳")[0].chars).toEqual(["㘳"]);
    expect(extractHeadwordClusters("#𠁕:")[0].chars).toEqual(["𠁕"]);
  });

  it("标题行、@页码、注释行不参与", () => {
    const gj = "@312\n\n# 康熙字典\n\n## 子集上\n\n### 一部\n\n#一古文#弌\n正文 // #丶 注释内不取";
    expect(extractHeadwordClusters(gj)).toEqual([{ raw: "#一古文#弌", chars: ["一", "弌"] }]);
  });
});

describe("resolvePageHeadwords", () => {
  const mk = (head: string) => `@x\n${head}\n正文`;
  const pages = [312, 313, 314, 315];
  const texts: Record<number, string> = {
    312: mk("#一古文#弌"),
    313: mk("#丁"),
    315: mk("#丂"),
  };

  it("本页有字头 → own", () => {
    expect(resolvePageHeadwords(mk("#丁"), 313, pages, texts)).toEqual({
      state: "own",
      clusters: [{ raw: "#丁", chars: ["丁"] }],
    });
  });

  it("纯延续页 → 最近前页的最后一组（清单有洞亦跳过）", () => {
    // 314 无字头：回溯 313（有），不更远
    expect(resolvePageHeadwords("@314\n续文", 314, pages, texts)).toEqual({
      state: "continuation",
      fromPage: 313,
      cluster: { raw: "#丁", chars: ["丁"] },
    });
    // 前页无字头时链式回溯：313 若也无 → 312 的最后一组
    const chain = resolvePageHeadwords("@314\n续文", 314, pages, { ...texts, 313: "@313\n续文" });
    expect(chain).toEqual({
      state: "continuation",
      fromPage: 312,
      cluster: { raw: "#一古文#弌", chars: ["一", "弌"] },
    });
  });

  it("宿主候选页文本缺失 → pending 报出所需页", () => {
    expect(resolvePageHeadwords("@314\n续文", 314, pages, { 312: texts[312], 315: texts[315] })).toEqual({
      state: "pending",
      needPages: [313],
    });
  });

  it("回溯到清单头仍无 → none；当前页未就绪 → loading", () => {
    expect(resolvePageHeadwords("@312\n续文", 312, pages, texts)).toEqual({ state: "none" });
    expect(resolvePageHeadwords(undefined, 313, pages, texts)).toEqual({ state: "loading" });
  });

  it("语料实况：@332/@333 回溯 @331「中」组", () => {
    const t331 = "@331\n#丫\n#㐄\n#(三)#中古文#𠁧#𠁩\n【唐韻】陟弓切";
    const index = [330, 331, 332, 333];
    const textsKx: Record<number, string> = {
      330: "@330\n#丨\n#丩\n#𠁡\n#个\n正文",
      331: t331,
      332: "@332\n民則不惑。（纯延续，无字头）",
    };
    for (const p of [332, 333]) {
      expect(resolvePageHeadwords(`@${p}\n纯延续正文`, p, index, textsKx)).toEqual({
        state: "continuation",
        fromPage: 331,
        cluster: { raw: "#(三)#中古文#𠁧#𠁩", chars: ["中", "𠁧", "𠁩"] },
      });
    }
  });
});
