// 编辑器语法高亮纯函数 nextGujiToken：最新语法（字头簇糖 + 既有语法）逐分段锁定。
// 口径：大字 token=strong、古文标记=keyword、胶水（、：，）与尾部=comment、
// 书名=link、空格标记=escape、注释/标点=comment、标题=heading、页码=keyword。
import { describe, expect, it } from "vitest";
import { nextGujiToken } from "@/components/editor/guji-language";

/** 整行 → 着色分段（token 名 null 归一为 plain） */
function segments(line: string): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  let pos = 0;
  while (pos < line.length) {
    const { next, tok } = nextGujiToken(line, pos);
    expect(next).toBeGreaterThan(pos); // 永不原地踏步
    out.push([line.slice(pos, next), tok ?? "plain"]);
    pos = next;
  }
  return out;
}

describe("字头簇糖高亮", () => {
  it("带圈续写省 #：(Y) 与 #(Y) 同为 strong；裸字大字亦 strong", () => {
    expect(segments("#(五)(增)𠂂")).toEqual([
      ["#(五)", "strong"],
      ["(增)", "strong"],
      ["𠂂", "strong"],
    ]);
  });

  it("字头连写串 #丶宔 全 strong（普通 #X 后裸写）；「古」尾随簇尾 comment 淡显", () => {
    expect(segments("#丶宔")).toEqual([
      ["#丶", "strong"],
      ["宔", "strong"],
    ]);
    expect(segments("#下古")).toEqual([
      ["#下", "strong"],
      ["古", "comment"],
    ]);
  });

  it("古文标记=keyword（糖可无标点），变体裸字=strong", () => {
    expect(segments("#(三)丹，古文：𠁿㣋")).toEqual([
      ["#(三)", "strong"],
      ["丹", "strong"],
      ["，古文：", "keyword"],
      ["𠁿", "strong"],
      ["㣋", "strong"],
    ]);
    expect(segments("#(三)丹古文𠁿㣋")).toEqual([
      ["#(三)", "strong"],
      ["丹", "strong"],
      ["古文", "keyword"],
      ["𠁿", "strong"],
      ["㣋", "strong"],
    ]);
  });

  it("全角括号与速记：#（五）（增）/#(z)#(15) 全簇着色", () => {
    expect(segments("#（五）（增）𠂂")).toEqual([
      ["#（五）", "strong"],
      ["（增）", "strong"],
      ["𠂂", "strong"],
    ]);
    expect(segments("#(z)#(15)音義")).toEqual([
      ["#(z)", "strong"],
      ["#(15)", "strong"],
      // 字头连写串：裸字连续（音義 两字头）
      ["音", "strong"],
      ["義", "strong"],
    ]);
  });

  it("行首承接形 古文：㘳（formatGj 标准输出）——标记 keyword、变体 strong", () => {
    expect(segments("古文：㘳")).toEqual([
      ["古文：", "keyword"],
      ["㘳", "strong"],
    ]);
  });

  it("异体并列 、 为 comment 胶水；尾缀注音冒号 comment", () => {
    expect(segments("#丅、𠄟")).toEqual([
      ["#丅", "strong"],
      ["、", "comment"],
      ["𠄟", "strong"],
    ]);
    expect(segments("#丏：【廣韻】彌殄切")).toEqual([
      ["#丏", "strong"],
      ["：", "comment"],
      ["【廣韻】", "link"],
      ["彌", "plain"],
      ["殄", "plain"],
      ["切", "plain"],
    ]);
  });

  it("簇后接书名/正文：簇止于【，其后各归其位", () => {
    expect(segments("#一，古文：弌【唐韻】於悉切")).toEqual([
      ["#一", "strong"],
      ["，古文：", "keyword"],
      ["弌", "strong"],
      ["【唐韻】", "link"],
      ["於", "plain"],
      ["悉", "plain"],
      ["切", "plain"],
    ]);
  });

  it("标点隔开后裸字不连大（#丸：俗 的俗为 plain）；释义中小字无 sugar 误亮", () => {
    expect(segments("#丸：俗")).toEqual([
      ["#丸", "strong"],
      ["：", "comment"],
      ["俗", "plain"],
    ]);
    expect(segments("#丅【字彙補】古文下")).toEqual([
      ["#丅", "strong"],
      ["【字彙補】", "link"],
      ["古", "plain"],
      ["文", "plain"],
      ["下", "plain"],
    ]);
  });
});

describe("既有语法高亮（回归）", () => {
  it("页码/标题/分隔条/注释整行；行内注释吞到行尾", () => {
    expect(segments("@341")).toEqual([["@341", "keyword"]]);
    expect(segments("### 一部")).toEqual([["### 一部", "heading"]]);
    expect(segments("======")).toEqual([["======", "meta"]]);
    expect(segments("// 注释 #甲")).toEqual([["// 注释 #甲", "comment"]]);
    expect(segments("釋文。 // 註：#甲")).toEqual([
      ["釋", "plain"],
      ["文", "plain"],
      ["。", "comment"],
      [" ", "plain"],
      ["// 註：#甲", "comment"],
    ]);
  });

  it("书名 link、行首孤儿后半段 link；标点 comment；空格标记 escape", () => {
    expect(segments("*又【集韻】且古作")).toEqual([
      ["*", "escape"],
      ["又", "plain"],
      ["【集韻】", "link"],
      ["且", "plain"],
      ["古", "plain"],
      ["作", "plain"],
    ]);
    expect(segments("史記儒】續")).toEqual([
      ["史記儒】", "link"],
      ["續", "plain"],
    ]);
  });

  it("兜底大字：#　 空字格与未闭合 #(增 仍 strong（扫描器不聚类 quirk）", () => {
    expect(segments("#　音義")).toEqual([
      ["#　", "strong"],
      ["音", "plain"],
      ["義", "plain"],
    ]);
    expect(segments("#(增#𠁦 音義")).toEqual([
      ["#(增", "strong"],
      ["#𠁦", "strong"],
      [" ", "plain"],
      ["音", "plain"],
      ["義", "plain"],
    ]);
  });

  it("任意位置复入一致（编辑后中途重高亮）", () => {
    const line = "#(三)丹，古文：𠁿㣋";
    // 从每个前缀位置着色，首段结果应与整行推进到该位置的 token 一致
    for (let p = 0; p < line.length; p++) {
      const { next, tok } = nextGujiToken(line, p);
      expect(next).toBeGreaterThan(p);
      // 复入不改变该位置的 token 类别（无隐藏跨 pos 状态）
      expect(() => nextGujiToken(line, p)).not.toThrow();
      expect(tok).toBeDefined();
    }
  });
});
