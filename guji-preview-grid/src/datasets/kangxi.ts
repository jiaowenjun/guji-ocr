// 康熙数据集入口及历史兼容适配器；通用解析器、布局引擎不依赖此模块。
import configJson from "../../../kangxi-gold/dataset-config.json" with { type: "json" };
import { applyBookLayout, importLegacyLayout } from "../ir/document-layout";
import { compileBookLayout, type BookLayout } from "../ir/layout-config";
import { gj2ir } from "../ir/gj2ir";
import type { IRDocument } from "../ir/types";
import { resolveDatasetConfig } from "./config";

export const KANGXI_DATASET = resolveDatasetConfig(configJson);
export const KANGXI_LAYOUT = Object.freeze(compileBookLayout(KANGXI_DATASET.layout.default.spec));

export function parseKangxiDocument(text: string): IRDocument {
  return applyBookLayout(gj2ir(text), KANGXI_DATASET.layout);
}

// 固定旧 v3 的历史口径；以后更新数据集预设也不能改变无快照旧文件的解释。
const LEGACY_KANGXI_BOOK: BookLayout = {
  default: {
    id: "kangxi-wuyingdian",
    revision: 1,
    spec: { schemaVersion: 1, bandsPerPage: 8, largeCellsPerBand: 12, smallRowsPerLargeCell: 2 },
  },
};

export function importLegacyKangxiDocument(doc: IRDocument): IRDocument {
  return importLegacyLayout(doc, LEGACY_KANGXI_BOOK);
}

/** 仅识别已知旧清单；其他书籍必须提供配置。 */
export function resolveDatasetIndexConfig(input: unknown, source: unknown) {
  return resolveDatasetConfig(input === undefined && source === "kangxi-gold" ? KANGXI_DATASET : input);
}
