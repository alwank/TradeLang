# TradeLang MVP 2 design verification


The original local screenshot links below are historical. Playwright cleared the shared output directory during the research terminal checks. The matching baseline and terminal screenshots for the redesign are available separately. [Research terminal release evidence](docs/plans/research-terminal/06-release-evidence.md)

The Option 2 mockups under [the design handoff](docs/plans/editor-visualizer/README.md) are the visual reference. The local browser app used the EMA Crossover and RSI Trend Recovery strategies on the same 35,064-candle synthetic dataset.

## Visual evidence

The desktop captures use a 1440 × 1024 CSS viewport at device pixel ratio 1. The 1487 × 1058 reference exports and 1440 × 1024 browser captures are scaled to matching 720 × 512 tiles for the full-view comparisons. The reference is on the left. In focused comparisons, the reference is on top. The editor and comparison were also captured at 390 × 844.

| State | Full view or focused evidence |
| --- | --- |
| Dataset form before import | [Import form comparison](apps/web/test-results/design-qa/dataset-import-comparison.png) |
| Imported dataset selected | [Dataset preview comparison](apps/web/test-results/design-qa/datasets-comparison.png) |
| EMA Crossover selected in the strategy library | [Library comparison](apps/web/test-results/design-qa/strategy-library-comparison.png) |
| Revision 3 with Explain open | [Editor comparison](apps/web/test-results/design-qa/strategy-editor-mvp2-comparison.png) · [Source focus](apps/web/test-results/design-qa/strategy-editor-mvp2-focus.png) · [Narrow editor](apps/web/test-results/design-qa/editor-narrow.png) |
| Active worker | [Running comparison](apps/web/test-results/design-qa/run-status-comparison.png) |
| Succeeded run with T000001 selected | [Overview comparison](apps/web/test-results/design-qa/run-overview-mvp2-comparison.png) · [Metrics and chart focus](apps/web/test-results/design-qa/run-overview-mvp2-focus.png) |
| Two succeeded runs selected | [Run history comparison](apps/web/test-results/design-qa/run-history-comparison.png) |
| Same-grid comparison | [Compare full view](apps/web/test-results/design-qa/compare-comparison.png) · [Metrics and chart focus](apps/web/test-results/design-qa/compare-focus.png) · [Narrow comparison](apps/web/test-results/design-qa/compare-narrow.png) |

## Findings and fixes

- **P2, results density.** In the [first Overview capture](apps/web/test-results/design-qa/baseline/run-overview-mvp2-comparison.png), the chart controls and full warning list displaced drawdown and trades below the desktop viewport. The run header now holds exports, concise warnings, and a details disclosure. The two charts share the lower time axis, and the trade inspector prioritizes execution, fill price, and net P&L. After one further spacing adjustment, the final capture shows both charts and the selected trade row together.
- **P2, comparison density and narrow layout.** In the [first Compare capture](apps/web/test-results/design-qa/baseline/compare-comparison.png), secondary metrics pushed the charts down and the narrow table clipped the second strategy. The four headline metrics lead the table, additional metrics are available below the plots, and the two-run table wraps to fit the narrow viewport.
- **P2, editor and dataset legibility.** The [first editor capture](apps/web/test-results/design-qa/baseline/strategy-editor-mvp2-comparison.png) showed small source text and an undivided explanation. The revised editor uses larger IBM Plex Mono source, wraps long lines on narrow screens, and groups the compiler's explanation into Entry, Exit, and Execution. The [first dataset capture](apps/web/test-results/design-qa/baseline/datasets-comparison.png) showed all returned sample rows and a wrapping fingerprint. The preview now shows the first and last samples, with the full fingerprint available through a disclosure.
- **P3, presentation details.** Native form controls and browser-rendered Inter differ slightly from the raster references. The type hierarchy, white and teal surfaces, selection contrast, and outlined focus remain legible. The mockups contain illustrative timestamps, row order, and chart geometry. The app renders stored timestamps and real unsmoothed curves. No decorative image assets are needed for these screens.

## Verification

- A Playwright run exercised import, draft creation, validation, save, explanation, submission, trade inspection, reload, and comparison with real artifacts. A keyboard test opened a diagnostic in an invalid Unicode draft and verified that the saved draft reopened. Browser checks found zero page errors and no page-level horizontal overflow at 390 px on the editor or comparison.
- The backend suite and additional comparison regression passed 803 checks in total. Coverage includes idempotency, frozen revisions, cancellation versus publication, interrupted-run recovery, result persistence after restart, exact-time comparison, and CLI/API result and fingerprint parity. A clean installed wheel migrated a fresh library and exposed the browser API. Ruff, mypy, the Next.js production build, and the strict MkDocs build passed.
- On the local 16 GiB Apple Silicon machine, the run status endpoint recorded a p95 of 11.8 ms across 111 requests while jobs were running. The first chart line rendered in 98–128 ms across five captures using 2,000 actual stored equity points. [Chart measurement](apps/web/test-results/design-qa/2k-chart.json)
- The in-app browser loaded the live comparison and run overview. The selected trade displayed the recorded 99.98 USDT exit fill and −111.59 USDT net P&L. The preview tab remains open at that result.

final result: passed
