# Strategy editor and backtest visualizer

The [research terminal handoff](../research-terminal/README.md) describes the current browser workspace. Use the [browser guide](../../browser.md) for the edit, validate, save, run, and inspect workflow.

The Option 2 mockups and acceptance notes on this page describe the first browser release. The [Price & Signals design](#price--signals-design) is the follow-up handoff for the bounded candle and indicator contract.

## Release sequence and mockups

| Milestone | Screen and build dependency |
| --- | --- |
| E01 · Browser shell | Use the Next.js/TypeScript shell and typed client generated from the pinned OpenAPI schema. Use the local API proxy and put **Strategies**, **Datasets**, **Runs**, and **Compare** in the header. Depends on D01. |
| E02 · Dataset import | [Import form](mockups/dataset-import.png) and [dataset library and preview](mockups/datasets.png). Depends on E01 and the D02 import API. |
| E03 · Strategy authoring | [Strategy library](mockups/strategy-library.png) and [CodeMirror editor](mockups/strategy-editor-mvp2.png). Depends on E01 and the D02 revision API. |
| E04 · Run status | [Running backtest](mockups/run-status.png). Depends on E02, E03, and D04's durable run lifecycle. |
| E05 · Backtest results | [Run Overview with trade inspector](mockups/run-overview-mvp2.png). Depends on E04 and D05's result artifacts and paging. |
| E06 · History and compare | [Run history](mockups/run-history.png) and [two-run comparison](mockups/compare.png). Depends on E05 and D05's comparison contract. |
| E07 · Release verification | Verify the browser flow, accessibility, performance, and recovery after E06 and D06's backend and parity gates pass. |

The [browser workspace](../../browser.md) uses the [local API](../../local-api.md#routes) for inspection, imports, revisions, queued runs, and comparison. The static mockups use verified metrics and fills from the synthetic examples. Chart geometry, save times, revision numbers, and in-progress states are illustrative. [EMA source](../../examples/02-ema.trade) · [RSI source](../../examples/01-rsi.trade) · [Synthetic candle generator](../../../scripts/example_data.py)

## Datasets and strategies

- **Import candles.** On **Datasets**, open **Import dataset** and show CSV/Parquet and the 100 MiB and 1,000,000-row limits before upload. Require explicit symbol, quote currency, and timeframe. Display the supported 24×7 calendar, bar-open timestamp convention, raw spot price basis, and base-quantity volume unit as fixed values. Default to **Reject gaps**. Explain next-observed-open fills, observed-row windows, and unavailable Sharpe for gapped windows when allowing gaps. [Candle data contract](../../candle-data.md)
- **Select an import.** Show progress as uploading or parsing and prevent duplicate submissions. A successful import shows UTC bounds, row count, first and last samples, fingerprint, and quality warnings. Explain reuse when the API returns a duplicate. On failure, show bounded row or column diagnostics and keep the failed import out of the dataset selector. **Select in editor** returns to the strategy with that import selected.
- **Open or create a strategy.** List the name, strategy header when different, current revision, last update, and last run status. Offer a blank strategy or one of the four original templates when creating. **Duplicate** creates an independent revision 1. **Archive** confirms removal from the active library and explains that saved run snapshots remain available.
- **Edit and validate.** Put CodeMirror on the left and **Diagnostics**, **Explain**, and **Assumptions** on the right. Show revision, save time, dirty state, and dataset beside **Save**, **Validate**, and **Run backtest**. Highlight syntax and offer deterministic completions from the grammar, registry, and earlier declarations. Use backend explanation text and assumptions, including the fee-inclusive entry budget. Show the resolved UTC window, warmup, gaps, and first executable open when the API supplies them.

## Run, inspect, and compare

- **Submit a saved revision.** Save can persist invalid source. Enable **Run backtest** when the current buffer matches the saved, validated revision, validation matches every selected input, and the worker is available. Volume Profile runs also freeze the lower-timeframe import used for inspection. Show revision, dataset fingerprint, capital, costs, first execution, and terminal policy in the assumptions inspector. Reuse the idempotency key on a retry or double click for the same submission. Poll the run from one second up to five seconds and stop at a terminal state. [Volume Profile inspection](../../local-api.md#validate-or-explain-source)
- **Read the result.** On a succeeded run, show its revision, dataset, UTC window, warnings, benchmark anchor, execution costs, engine and semantics versions, and any open position. **View strategy** opens the executed revision read-only. Provide full-resolution exports for source, manifest, summary, equity, trades, and events. Show the strategy and warmup-aligned buy-and-hold on synchronized equity and drawdown charts. Offer quote money or index 100, **Reset zoom**, and a sampling label with higher-resolution data on zoom. Use stored metrics and label null values **Unavailable** with their reason. [CLI result fields](../../results.md#artifact-files)
- **Audit a trade.** Page closed trades in entry order and filter by exit reason. The selected row opens the right inspector with quantity, reference and fill prices, costs, net return, signal values, protection levels when applicable, and linked events. Keep opening fills distinct from intrabar fills. For an intrabar fill, show **Within candle** and the containing candle's UTC opening time.
- **Compare saved runs.** Filter **Runs** by strategy, dataset, or status. Select two to four succeeded runs and return to the selection through **Change runs**. Put differences and benchmark entry times before the charts. Show full-run metrics, actual monetary values, and curves indexed to original starting capital. Use shared timestamps for equal grids and offer the exact timestamp intersection for compatible runs on different grids. Keep tables and explain the reason when overlays are unavailable because of incompatible runs or no overlap.

## Price & Signals design

The [Price & Signals mockup](mockups/price-and-signals.png) and [Overview with the chart link](mockups/run-overview.png) show the approved candlestick workflow. It follows the E05 release screen when the backend can serve bounded candle and indicator ranges from a successful run. Current bundles include input candles and fill events. Full per-candle indicator output requires a new result contract. [Artifact fields](../../results.md#read-the-artifact-fields) · [Indicator readiness](../../indicators.md)

- Serve the immutable run's candles and core-computed series for indicators referenced in the executed strategy. Carry a stable series key, label, unit, candle index, UTC open time, and value or unavailability. Deduplicate identical calls and retain field selectors and lookbacks in the plotted expression. Use the original run history to compute values before slicing the chart range.
- Overlay price levels on candles and put oscillators, price distances, and other scales in shared-time-axis panes. Draw gaps in candles and unavailable indicator values as breaks. Join a fill to its candle by `bar_open_at` and plot its recorded price. Use event IDs and sequence to distinguish fills and signals at the same timestamp.
- **View on chart** opens the exit candle and preserves the selected trade in the inspector. Selecting an entry or exit marker updates the inspector with phase, price, reason, and available signal values. Preserve an explicitly selected UTC range when switching tabs. Direct entry defaults to the last 100 observed candles, or the full window when shorter.

## States

[State mockups](mockups/interaction-states.png) show an invalid draft, an interrupted run, indicator warmup, and a run with zero closed trades.

| State | Display and recovery |
| --- | --- |
| Unsaved or invalid source | Show revision, dirty state, and any current diagnostics. Keep **Save** and **Validate** available. Use **Save revision to run** for a dirty buffer and show why Run is unavailable. Preserve the buffer on a failed save. |
| Save conflict | Retain the editor buffer. Offer **Reload server version** and **Copy local source**. |
| Loading, offline API, queue full, or worker unavailable | Keep the current form or draft. Show inline status and offer a retry when the service can accept one. |
| Queued or running | Show frozen context and **Cancel run**. Show a queue position or progress only when the worker reports it. |
| Interrupted, failed, or cancelled run | Keep the revision and dataset visible and show the outcome in place of charts. Offer **View strategy** and **New run**. |
| Zero closed trades | Keep available run metrics and curves visible. Put **No closed trades** in the table body. Offer **View open position** when one exists. |
| Indicator warmup in Price & Signals | Keep candles visible. Leave the affected series blank until its first valid output. The tooltip labels the affected value **Warming up**. |

## First browser release layout and acceptance

Use a light theme with white work surfaces, `#F3F7F6` inspectors, `#172D39` text, and `#087269` actions. Use Inter for the interface and IBM Plex Mono for source and tabular values. At the 1440 × 1024 design viewport, use a 70/30 work area and inspector split. Below 960 CSS pixels, stack them in reading order and let the action row wrap. Keep 32 px outer gutters on wide screens and 16 px on narrow screens. Use a single divider between surfaces, underlined active tabs, and a visible focus ring. [TradeLang docs palette](../../stylesheets/tradelang.css)

- From a fresh local library, import candles, create a strategy, validate and save it, submit it, and inspect benchmark and trade details. Run a second strategy and compare the results. Reload and restart to verify saved revisions and run history. Edit a newer revision while a job is active and verify the run retains the submitted revision.
- Change datasets during validation, including a lower-timeframe input when applicable. Discard out-of-order responses for prior source or dataset selections. Check that diagnostic spans focus correctly across Unicode, tabs, and line breaks and that navigation from a dirty buffer offers **Stay** or **Leave without saving**.
- Complete the editor-to-compare path using only the keyboard. Check focus order, focus return, announced errors, a labeled display-only timezone control with UTC as default, and visible chart and table alternatives. Check narrow widths and verify that color has a text or shape equivalent.
- Exercise an oversized or invalid upload, a revision conflict, offline API, queue full, cancellation, interruption, zero trades, unavailable metrics, and no-overlap or incompatible comparisons. Verify API/CLI result parity and record chart and status API performance against the backlog's release targets.
- When the Price & Signals contract is available, jump from the T000001 trade inspector to its exit candle. Check that both tabs retain the same run, dataset, trade, and selected time range, and that inactive or warming-up series do not create chart values.
