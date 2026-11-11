// 内置示例文档，内容取自 vscode-guji-preview/example/ 下的 .gj 原文
import kangxi0312 from "./kangxi-0312.gj?raw";
import kangxiYibu from "./kangxi-yibu.gj?raw";

export interface Sample {
  id: string;
  name: string;
  description: string;
  content: string;
}

export const samples: Sample[] = [
  {
    id: "kangxi-0312",
    name: "康熙字典 · 三一二",
    description: "单页示例：子集上「一部」",
    content: kangxi0312,
  },
  {
    id: "kangxi-yibu",
    name: "康熙字典 · 子集上一部",
    description: "多页示例（17 页）：一部全部字头",
    content: kangxiYibu,
  },
];
