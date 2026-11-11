// 导出自包含 HTML：复刻 vscode-guji-preview 插件 Webview 的产物形态
// （单文件、无外部依赖，guji.css 内联进 <style>）
import { renderToStaticMarkup } from "react-dom/server.browser";
import gujiCss from "@/guji.css?raw";
import { Pages } from "@/components/guji/Pages";
import type { PageModel } from "@/components/guji/model";

export function buildHtml(pageModels: PageModel[], scale = 25): string {
  const body = renderToStaticMarkup(<Pages pageModels={pageModels} />);
  const scaleCss = `:root { --guji-scale: ${scale}px; }`;
  return `<!DOCTYPE html>
<html lang="zh-Hans">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>古籍</title>
  <style>
${scaleCss}
${gujiCss}
  </style>
</head>
<body>
${body}
</body>
</html>`;
}

export function downloadHtml(pageModels: PageModel[], filename = "guji.html", scale = 25) {
  const html = buildHtml(pageModels, scale);
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
