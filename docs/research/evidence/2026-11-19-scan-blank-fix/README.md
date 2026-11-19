# 427 页原图空格识别修复证据

对应 [修复报告](../../2026-11-19-427页原图空格识别修复报告.md)，日期 2026-11-19。

## 最终证据

| 文件 | 用途与边界 |
| --- | --- |
| [verified-results.json](verified-results.json) | 报告阶段直接调用冻结旧、新 API 的 116 页回放；含原图／源码哈希、网格、完整空格集合、G/L/B 归因；116 页全部与历史最终结果一致 |
| [summary.json](summary.json) | 页数分类、数量变化与仍存在问题的摘要，不替代完整坐标 |
| [replay.py](replay.py) | 复跑入口，读取清单原图及冻结行跨度；不改标注。运行后写 verified-results.json |
| [ocr_scan_before.py](ocr_scan_before.py)、[scan_grid_before.py](scan_grid_before.py) | 与 Git `6bbd4bbe06b392fd22dee2bee72312009da7dc45` 一致的修复前源码 |
| [ocr_scan_after.py](ocr_scan_after.py)、[scan_grid_after.py](scan_grid_after.py) | 报告时修复后源码快照，仅作复现依据；实际功能由 tools/dataset 维护 |
| [input-priors.json](input-priors.json) | 修复开始时 116 页草稿行跨度与大字位置；旧算法使用这些输入，新算法忽略跨度 |
| [prior-verification.json](prior-verification.json) | 当前转写重建跨度的核验：115 页相同，427 页后来已经修改 |
| [historical-final-results.json](historical-final-results.json) | 上一轮最终输出快照；已去除从中间审计继承而未更新的 mask_added/mask_removed，避免误读 |
| [p427-original-and-star.json](p427-original-and-star.json) | 旧算法下初始草稿 12 格与仅补首个 * 后 17 格的原始结果 |
| [p427-priors.json](p427-priors.json) | 上述两种旧草稿的输入跨度 |
| [p427-book-rule-pixels.json](p427-book-rule-pixels.json) | 两目标格的采样框、阈值、过滤前后墨迹数量 |
| [remaining-limitations.json](remaining-limitations.json) | 363/399 纸斑、390 大字局部留白、398 印章边线的前后采样证据；问题已暂缓实施，后续机制与验收条件见[遗留问题与后续方案](../../2026-11-19-原图空格识别遗留问题与后续方案.md) |

## 后续 445 页回归诊断

445 页不在原 312–427 页审计范围内。同图同稿重放确认：旧版 12 格，新版 13 格，唯一新增 `(4,1,1)` 是列首居中“文”的右半格误报。改变纵向网格即可触发，框线过滤未删除该格任何墨迹。此处保留诊断基线；后续已实施修复，见[居中小字修复证据](../2026-11-19-centered-small-fix/README.md)。

- [p445-analysis.json](p445-analysis.json)：完整新旧输出、阶段归因、像素统计、原图及源码哈希；包括冻结修复后实现与诊断时生产实现结果一致的核验。
- [p445-input.json](p445-input.json)、[p445-layout.json](p445-layout.json)：从诊断时草稿生成的旧接口跨度和布局快照。
- [replay_p445.py](replay_p445.py)、[p445-verified.json](p445-verified.json)：专用重放入口与已验证输出。
- [新旧采样范围对照图](../../figures/2026-11-19-scan-blank-fix/p445-before-after.png)：蓝框为小格，红框为目标格核心采样区。
- [p466-boundary-frame.json](p466-boundary-frame.json)：466 页底框与末行普通小字粘连导致大字保护误判的像素、前后结果及 156 页回放摘要。

## 中间版本证据

- [intermediate-no-large-mask.json](intermediate-no-large-mask.json)：最初去掉大字保护后的候选；所列 `large_candidates` 用当时草稿作诊断交叉检查，不是图像金标。427 的这一诊断也包含草稿错位，因此不能直接把整列候选都算作误报。
- [intermediate-audit.json](intermediate-audit.json)：第一版图像大字保护的全页审计，保留当时回归。此处 `found`、`mask_*` 只描述该中间版本，不能用作最终结果。
- [图像证据目录](../../figures/2026-11-19-scan-blank-fix/)：427 三阶段对照、采样框、中间回归、最终全量差异裁片、剩余限制放大图。`audit-diffs.jpg` 和 `latest-diffs.jpg` 属中间版本；`final-diffs.jpg` 才是最终差异图。

`replay.py` 需要 NumPy、Pillow、仓库未改动的定位依赖和清单中的原图。冻结的 Python 文件本身保留原文，它们的相对导入由回放器显式配置；不要直接把证据目录中的 API 文件当成生产入口执行。未来重放须检查输入与依赖哈希，报告不是随当前草稿变化的实时状态页。

本证据没有提供全部 102 页的人工逐格真值；检测数量、集合一致和测试通过均不等于准确率或全页终校。报告明确记录了仍未解决的跨页影响。
