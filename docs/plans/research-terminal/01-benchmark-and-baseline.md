# Benchmark and current workspace

This benchmark covers the repeated research loop of writing a strategy, validating it against a dataset, running a backtest, and inspecting or comparing the result. The peer evidence comes from public vendor documentation. The TradeLang baseline comes from the current working tree and the existing local design QA captures. The local preview could not start during the benchmark, so the captures describe the recorded MVP 2 state and do not establish fresh browser measurements.

## Peer patterns

| Reference | Observed pattern | TradeLang application | Evidence |
| --- | --- | --- | --- |
| QuantConnect Algorithm Lab | The IDE has a bottom console and Problems tab. Backtests open in a results tab, with performance, trades, orders, and logs. | Separate source, problems, and run output into stable workspace areas. Give a run a direct address and link to its executed revision. | [IDE](https://www.quantconnect.com/docs/v2/cloud-platform/projects/ide#06-Console) · [Run backtests](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/getting-started#02-Run-Backtests) · [Results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results) |
| TradingView Pine Editor | The editor can dock beside the chart or stack below it. The Strategy Report provides metrics and a trade ledger, and executed orders also appear on the chart. | Make equity, drawdown, and trades easy to inspect together. Reuse the selected run and trade when the planned candle view becomes available. | [Pine Editor](https://www.tradingview.com/support/solutions/43000763320-how-to-work-with-pine-editor/) · [Strategy Report](https://www.tradingview.com/support/solutions/43000764138-tradingview-strategy-report-how-to-start/) · [Strategies and order markers](https://www.tradingview.com/support/solutions/43000562362-what-are-strategies-backtesting-and-forward-testing/) |
| AmiBroker Analysis | The formula, symbol scope, time range, and backtest action are grouped above a results list. | Put the selected dataset, revision, and run controls together. Show a concise run input summary adjacent to the controls. | [Analysis window](https://www.amibroker.com/guide/w_analysis.html) |
| Interactive Brokers TWS Mosaic | Panels can share a symbol context, and the user can resize and arrange them. | Bind the run header, charts, trade ledger, and inspector to one run and selection. Give each panel a clear title and collapse affordance. | [Mosaic walkthrough](https://www.interactivebrokers.com/campus/trading-lessons/getting-started-with-tws/) · [Window linking](https://www.interactivebrokers.com/support/faq/content/link-unlink-tws-windows-together-34485128) |

TradeLang's own strengths are its concise strategy language, compiler-backed **Explain**, immutable run inputs, and an auditable path from a trade to its fills and events. Use those capabilities to define the workspace. [Existing browser design](../editor-visualizer/README.md) · [Browser workflow](../../browser.md)

## Current screens and changes

| Screen | Observed in the baseline | Redesign requirement |
| --- | --- | --- |
| Shell and landing | A wide top navigation bar, page-scale headings, and generous gutters set the rhythm across routes. The root route opens the Strategies library. | Use one compact workspace shell across all current screens and keep the Strategies library as the landing page. |
| Strategy library and revisions | The library offers search and creation, and executed revisions have a read-only route. | Give the landing page a dense strategy list with an obvious **New strategy** action. Bring executed source into the same visual system with a visible read-only revision label. |
| Datasets and run history | Dataset import and preview have their own view. History uses a filter row, a run table, and a selected-run inspector. | Use shared table, selection, and inspector patterns. Keep quality warnings, run status, and the selection for comparison visible where users act on them. |
| Editor | The existing 1440 × 1024 capture places the first source line at roughly y=350 after several rows of chrome. CodeMirror, line-level diagnostics, and Explain already exist. | Put source and run actions first. Move problems into a dedicated dock and retain Explain and Assumptions beside the editor. |
| Run lifecycle | The editor normally navigates to `/runs/{id}` after a successful submission. If the source changed during submission, it can instead link to the submitted run. | Keep the editor and acknowledged backtest within reach and preserve both the draft and the exact run identity. |
| Results | The overview shows headline metrics, synchronized equity and drawdown, and an audit inspector. In the existing desktop capture, the first trade row is near the bottom edge. | Fit headline metrics, meaningful plots, and a usable trade ledger into the first desktop viewport. Keep sampling, units, warnings, and run inputs visible. |
| Compare | Full-run metrics and normalized curves already exist. Timestamp alignment sits below the metrics, and input differences live in the side inspector. | Show alignment and material input differences before the curves. Pin a reference run and expose signed deltas beside actual values. The pinned run is a TradeLang design choice for comparing strategy iterations. |

Implementation references [Shell](../../../apps/web/src/components/shell.tsx), [styles](../../../apps/web/src/app/styles.css), [editor](../../../apps/web/src/components/strategy-editor.tsx), [run detail](../../../apps/web/src/components/run-detail.tsx), [run overview](../../../apps/web/src/components/run-overview.tsx), and [compare](../../../apps/web/src/components/compare-runs.tsx).

## Measure before and after

Use one repeatable local fixture and record the viewport, theme, run inputs, and selected trade. Capture desktop at 1440 × 900 and laptop at 1280 × 800 before implementation and at each review gate. Measure where the first source line, diagnostic list, chart, and first trade row begin. Record the steps and focus transitions for **edit → validate → save → run → inspect → resume editing**. The historical QA capture used a taller viewport, so collect a matched baseline before claiming a pixel or task-time improvement. [Existing design QA](../../../design-qa.md)
