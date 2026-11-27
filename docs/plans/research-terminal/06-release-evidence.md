# Research terminal release evidence

The release checks use the supervised loopback API with a fresh library for the golden workflow and a copy of the existing preview library for matched captures. See the acceptance criteria in the release checklist. [Verification and release](04-verification-and-release.md)

## Matched browser captures

The baseline and release captures use the same saved EMA Crossover source, dataset, run and trade selection. The baseline submitted runs to standalone result routes. The terminal acknowledges the run in the editor dock and opens the result on demand.

| State at 1440 × 900 | Baseline light | Terminal light and Graphite |
| --- | --- | --- |
| First source line from viewport top | 334 px | 157 px |
| Open Problems panel from viewport top | Diagnostics in the inspector | 778 px |
| Trade ledger heading from viewport top | 893 px | 705 px |
| Bottom of the third trade row | 1,139 px | 864 px standalone, 882 px in the strategy workspace |

The 29 baseline captures and 65 terminal captures cover the main routes. The terminal captures use 1440 × 900, 1280 × 800, 1024 × 768, and 390 × 844 CSS viewports. Chromium's native 200% zoom reduced a 1440 × 900 viewport to 720 × 450 CSS pixels. The sampled routes had zero page-level horizontal overflow at native zoom. The browser regression also checks long unbroken strategy labels and dataset filenames.

Local artifacts are under `runs/research-terminal-evidence/`. Each capture's viewport, theme, route, fixture identity, and selected trade appear in `before/checks.json` and `after/checks.json`. The open-inspector result captures select **T000001**. The active editor and in-workspace result are in `after/graphite-1440x900-editor-ready.png` and `after/graphite-1440x900-workspace-result.png`.

| Fixture | Identity |
| --- | --- |
| 35,064-candle deterministic hourly sample | Dataset `e83dbbdb-b526-46dd-84a0-c11d712672a5` from the existing preview library |
| EMA Crossover, revision 3 | Run `2a8891f4-a740-46e6-ad54-7ed771486f25` |
| RSI Trend Recovery, revision 1 | Run `fee4b671-9e96-466f-bbc4-45ee5bf98a24` |
| Queued EMA Crossover | Run `3210ae9c-8df3-4b93-b9aa-b8bb35001ded` with the worker paused during capture |
| Golden ledger | `docs/fixtures/core.trade` and `docs/fixtures/core.csv` in a fresh temporary library |

## Workflow and integrity

- The browser suite exercises the Strategies landing page, dataset import and recovery, duplicate and archive, saved revision source, keyboard diagnostic selection, the run dock, result inspection and export, and comparison.
- Delayed requests exercise edits during Save, stale revision conflicts, primary and Volume Profile selection changes, and a lost submission response. The retry reuses its key after refresh. The dock and result share the read stream and keep the last known state through a failed read.
- The golden browser run records final equity of **1,090.91 USDT** and T000001 entry and exit fills of **110 USDT** and **120 USDT**. The trade inspector shows the linked fill event and the export returns the full curve. The sample captures cover sampling, the warmup-aligned benchmark, an open position, and a multi-row ledger.
- The supervised lifecycle check fills the queue, confirms that validation survives a capacity response, and verifies an unavailable worker, queued and active cancellation, failed execution, and worker interruption. The result opens its saved source after interruption. Chart zoom, reset, and the chart-data table also pass. See `lifecycle.json` in the artifact directory.
- The comparison cases use two, three, and four succeeded runs. They exercise exact and intersecting timestamps, an unavailable overlay, pairwise deltas with a mismatched third run, a different starting capital, and URL pin retention and fallback.
- After a supervised API restart, the copied library reopens its saved strategy, dataset, executed revision, and both newly recorded sample results. Two bundles already in that preview library have manifest run IDs that differ from the IDs in their library rows. The API rejected both in the pre-redesign baseline with `E_RUN_ARTIFACT`. The matched captures use freshly published runs of the same strategies and data. The original bundles remain in the library.

## Accessibility and performance

The WCAG A and AA axe-core scan reported zero violations for Strategies, Datasets, the editor, saved revisions, Runs, a selected-trade result, and Compare in both Graphite and Light. The recorded accessibility trees include the editor, read-only source, tabs, status text, chart alternatives, and the trade inspector. See `accessibility.json` and `after/native-zoom.json` in the artifact directory.

Chromium on macOS and Ubuntu Linux exercised the editor shortcuts. The Linux keyboard run completed save, validate, submit, open, inspect, return, undo, redo, and baseline pinning. Firefox with Orca 46.1 read the strategy landmarks, source entry, validation announcements, queued-run acknowledgement, run link, selected trade state, and baseline selector and value. See `linux-keyboard.log` and `orca-workflow.log` in the artifact directory.

With 2,000 stored equity marks on the same host, the median from equity response to the first plotted line was 94.9 ms before and 95.5 ms after. Each median uses five production-build page loads. Direct status reads during three active 35,064-candle runs had a p95 of 5.6 ms across 802 requests. The raw samples are in `before/2k-chart.json`, `after/2k-chart.json`, and `status-latency.json`.

Playwright writes test output to `apps/web/test-results/playwright`. Its earlier shared output directory was cleared during the first verification run, removing the local MVP 2 screenshots. The current before-and-after captures use the separate evidence directory.

The regenerated OpenAPI document, generated TypeScript types, and browser language catalog match the workspace files byte for byte. Type checking, the Next.js production build, strict MkDocs, Ruff, mypy, all 11 browser tests, and all 803 backend tests pass. [Browser workflow](../../browser.md)
