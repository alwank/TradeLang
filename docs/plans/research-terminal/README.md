# TradeLang research terminal redesign

Convert the existing local web workspace into a desktop-first research terminal. The primary workflow is **edit → validate → save → run → inspect → resume editing**. Keep the editor, current run, and evidence for an execution within easy reach. Ship the full redesign in one release across Strategies, the editor and read-only revisions, Datasets and import, Runs and results, and Compare.

**Status** · Implementation plan with product decisions confirmed on November 22, 2026. See the backlog for the build order and the shared release gate.

## Read in order

| Document | Use it to |
| --- | --- |
| [01 · Benchmark and current workspace](01-benchmark-and-baseline.md) | Trace the redesign to QuantConnect, TradingView, AmiBroker, and TWS and measure the current workflow. |
| [02 · Workspace and interaction design](02-workspace-and-interactions.md) | Build the shell, panes, toolbars, status and error states, results, and visual system. |
| [03 · Frontend architecture and state](03-frontend-architecture.md) | Implement routing, draft lifetime, submission, shared polling, and API reuse in `apps/web`. |
| [04 · Verification and release](04-verification-and-release.md) | Verify the real workflow, responsive layout, accessibility, and result integrity. |
| [05 · Implementation backlog](05-implementation-backlog.md) | Work through the changes in small slices with dependencies and merge criteria. |
| [06 · Release evidence](06-release-evidence.md) | Review measured layouts, workflow and result checks, and performance. |

## Confirmed decisions

| ID | Decision | Confirmed direction |
| --- | --- | --- |
| D01 | Release scope | Ship the redesigned shell and all existing browser screens together. Build and verify them in smaller slices. |
| D02 | Start page | `/` always opens the Strategies library. Explicit strategy, run, and comparison links open their targets. |
| D03 | After submitting a run | Stay in the editor and show the acknowledged run in the bottom dock. **Open run** switches to its result view. |
| D04 | Unsaved source | Use explicit Save for revisions and recover dirty source after refresh in the same browser tab. |
| D05 | Theme | Graphite dark by default with a light option. |
| D06 | Panes | Collapsible panes with remembered visibility. |
| D07 | Viewports | Desktop and laptop first with a usable stacked layout at narrow widths. |
| D08 | Keyboard | Scoped shortcuts for Save, Validate, Run, and pane navigation. |
| D09 | Compare | Compare two to four succeeded runs, pin one as the baseline, and show signed metric deltas. Put alignment and input differences ahead of plots. |
| D10 | Price & Signals | Follow up after the bounded candle and indicator data contract. |

## Existing contracts that govern the redesign

- Save creates a revision. Run uses the saved, validated source and the exact chosen datasets. The worker records an immutable run snapshot, and an executed-source view remains read-only.
- Use actual result values, timestamps, and fills. Keep warmup and sampling labels, chart data alternatives, timestamp precision, and export links available.
- Keep current durable URLs and local library behavior. Compare keeps its existing eligibility and exact timestamp alignment rules.
- The terminal work targets the web UI and its documentation. Changes to grammar, registry, execution semantics, and the run artifact format require their own scope.

[Existing browser design](../editor-visualizer/README.md) · [Browser workflow](../../browser.md) · [Local API](../../local-api.md) · [Execution semantics](../../execution-semantics.md)

## Definition of success

At 1440 × 900, source, run actions, and diagnostics are visible together. Results show headline metrics, equity, drawdown, and several trade rows in the first view. A user can submit a run, inspect it, and resume the same editor buffer and caret using only the keyboard. Compare shows which run is pinned and how each comparable metric differs. Every existing browser route uses the terminal shell and opens its exact saved source or result where applicable. [Verification criteria](04-verification-and-release.md)
