// 导出自包含 HTML：复刻 vscode-guji-preview 插件 Webview 的产物形态
// （单文件、无外部依赖，flex.css + matrix.css 内联进 <style>，两种视图均可导出）
import type { ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server.browser";
import flexCss from "@/flex.css?raw";
import matrixCss from "@/matrix.css?raw";

export function buildHtml(body: ReactElement, scale = 25): string {
  const bodyHtml = renderToStaticMarkup(body);
  const scaleCss = `:root { --guji-scale: ${scale}px; }`;
  return `<!DOCTYPE html>
<html lang="zh-Hans">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>古籍</title>
  <style>
${scaleCss}
${flexCss}
${matrixCss}
  </style>
</head>
<body>
${bodyHtml}
</body>
</html>`;
}

export function downloadHtml(
  body: ReactElement,
  filename = "guji.html",
  scale = 25
) {
  const html = buildHtml(body, scale);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
