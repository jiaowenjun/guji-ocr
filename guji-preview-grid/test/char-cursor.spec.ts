import { describe, expect, it } from "vitest";
import { parseKangxiDocument } from "../src/datasets/kangxi";
import { buildCharIndex, charCursorTarget } from "../src/ir/linkage";
import type { IRDocument } from "../src/ir/types";

describe("渲染字格反向定位", () => {
  const source = "@1\n#甲\n乙丙";

  it("无源码的 IR 和不存在的字格不误跳到文档开头", () => {
    const doc = parseKangxiDocument(source);
    const index = buildCharIndex(doc);
    const noSource: IRDocument = JSON.parse(JSON.stringify(doc), (key, value) =>
      key === "src" || key === "cpSrcs" ? undefined : value);
    expect(charCursorTarget(buildCharIndex(noSource), source, index[0].target)).toBeNull();
    expect(charCursorTarget(index, source, { kind: "large", elId: "missing" })).toBeNull();
    expect(charCursorTarget(index, "", index[0].target)).toBeNull();
  });
});
