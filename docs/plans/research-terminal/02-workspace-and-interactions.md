# Workspace and interaction design

Design the desktop experience around the source and the result. Use the current TradeLang wording for strategy, dataset, revision, backtest, and trade. Keep the compiler's Explain view visible as a practical way to verify how TradeLang reads a strategy. Apply the [confirmed decisions](README.md#confirmed-decisions) across the existing terminal screens.

## Shared shell

| Region | Desktop behavior | Narrow behavior |
| --- | --- | --- |
| Workspace header | A 44 px starting target for product name, active workspace context, and global display preferences. Keep route names and panel controls visible or accessible via their labeled menus. | Wrap the strategy context and actions into two rows when needed. Keep Run visible with its disabled reason. |
| Left navigation | A compact rail for **Strategies**, **Datasets**, **Runs**, and **Compare**. Give each item an accessible name and a text label in expanded mode. On a strategy screen, a collapsible list can switch strategies or return to the full library. Start with a 200–224 px expanded list. | Show navigation as a compact row or a labeled menu. Use a full-width panel for browsing the library. |
| Main workspace | Source and the currently open backtest occupy the primary canvas. Use compact route links styled as workspace tabs, with the active view exposed to assistive technology. | Show one main view at a time. Keep the selected run or source route reachable with a labeled control. |
| Right inspector | Start at 300–340 px when there is room. Collapse on demand and remember the user's choice. Give an active trade or an explicit Explain action a clear way to reveal the inspector. | Put inspector content after the primary content or offer an explicit disclosure next to the selected item. Return focus to its opener on close. |
| Bottom dock | **Problems** and **Runs** beneath source. In a succeeded run, the trade ledger occupies the bottom region. Give the dock a labeled collapse control and a visible status even while collapsed. | Use sections that stack and expand in document order. Avoid a fixed-height dock on short screens or while the software keyboard is open. |

At 1200 CSS px and above, start with the full multi-pane layout. At 960–1199 px, collapse secondary space first and keep the editor and inspector usable. Below 960 px, use a stacked layout and local overflow for wide tables and long source. Tune the breakpoints against real labels at 200% zoom. Each desktop pane that scrolls needs a clear title and visible focus, and hidden panels must leave the keyboard tab order.

## Editor and submission

1. Display the strategy name, current saved revision, and **Saved** or **Unsaved changes** in compact chrome. Place primary dataset, symbol, timeframe, and **Save**, **Validate**, and **Run backtest** in the contextual toolbar. Reveal the lower-timeframe dataset field when required by the existing Volume Profile flow. Use a visible way to expand truncated input labels or inspect full dataset metadata.
2. **Problems** groups compiler and data errors and warnings with counts, code, message, and line when supplied. Activate a source diagnostic to reveal the editor, select the span, and focus CodeMirror. Display diagnostics without source spans as text. Surface failed validation in the dock and announce it without taking focus from the user's current control. If the user collapsed the dock, expose the problem count and a direct reveal action.
3. **Explain** uses backend text and groups Entry, Exit, and Execution. **Assumptions** presents the resolved window, warmup, first executable open, costs, gaps, and terminal policy when supplied. Changing source or any selected input invalidates prior inspection and readiness immediately. An unavailable value gets the engine's explanation when supplied.
4. Save remains a deliberate, revision-creating action and accepts invalid source. Validate checks the current buffer and selected data. Run is enabled only for a clean, saved revision with matching, compatible validation and an available worker. Show the current blocker next to the run command, including Save first, select data, validate, or worker unavailable.
5. On acknowledgement, show the run in the bottom **Runs** dock and announce its status once. Switch an expanded dock to Runs when focus is outside it. When the dock is collapsed or focus is already inside Problems, show a visible, labeled run status and **Open run** in the dock strip. Stay in source and preserve focus, caret, scroll, and undo. Opening the result by click or keyboard moves focus to its heading. Switching back to the source restores the previous editor selection and scroll position.
6. Suggest `Cmd/Ctrl+S` for Save, `Cmd/Ctrl+Shift+Enter` for Validate, and `Cmd/Ctrl+Enter` for Run while the editor workspace is active. A shortcut uses the same gating and handlers as the button. Keep standard tab order and arrow navigation inside actual pane tab lists. Add a visible, conflict-checked pane-focus shortcut in review, with an equivalent button or landmark route. Ignore shortcuts during IME composition, in unrelated form fields, and when a modal is active. Show shortcut labels in a small help disclosure rather than adding permanent copy beside every action.

## Run status and results

| State | Content and recovery |
| --- | --- |
| Starting, queued, running | Show exact revision, dataset, submission time, and backend status. Show progress only when reported. Provide **Cancel run** for eligible states and use a single shared status across the dock and result. |
| Cancelling, cancelled, failed, interrupted | Show the requested cancellation state until the API reports a final outcome. Surface the human-readable failure and actionable recovery. For an interrupted job, show its recorded reason and link to the saved source and a path to start a new run. |
| Succeeded | Put return, final equity, max drawdown, and closed trades into a compact strip above synchronized equity and drawdown. Show the window, units, benchmark and sampling labels, and visible warning summaries. Keep the run metadata, executed revision, exports, chart data table, zoom, and display timezone accessible. |
| Selected trade | Highlight the ledger row and show fill, costs, P&L, reason, prices, signal values, and available linked events in the inspector. When a filter removes the selection, clear the inspector with a short explanation. Keep within-candle precision explicit. |
| No closed trades or unavailable metric | Keep valid curves and metrics visible. Show **No closed trades** in the ledger and **View open position** when available. Show **Unavailable** with its supplied reason and a clear visual distinction from zero. |

Switching between results scopes every selection and request to its run ID. Keep events and secondary detail on demand. Closing results returns to the prior workspace view. Selecting a trade never changes the input dataset or source revision. Highlight the same trade on Price & Signals only when the run-scoped candle and indicator contract ships. [Existing price-and-signal behavior](../editor-visualizer/README.md#price--signals-design)

## Strategy, dataset, history, and compare views

- **Strategies** is the landing page every time the user opens `/`. Keep search, templates, duplicate, and archive. Show revision and last run in the table and preserve the executed-revision route for archived strategies.
- **Saved revision** shows the exact read-only source with strategy name, revision number, and source metadata. Use the same CodeMirror theme and keyboard-readable source as the editor, with a visible read-only label.
- **Datasets** keeps import and quality verification. Use dense preview rows and an inspector for metadata and fingerprints. Preserve dataset choices and failure details while the user fixes an import.
- **Runs** keeps strategy, dataset, and status filters plus two-to-four selection of succeeded runs. Use legible status text, a sticky header where the table scrolls, and aligned numeric columns.
- **Compare** summarizes actual timestamp alignment and material input differences above the curves. Show dataset, fees, time range, and other differences only when returned for the selected runs. Link to source revisions and original run results. Keep the current full-run metric labels and separate the chart overlap window from metric coverage.

## Pin a comparison baseline

Use a labeled **Baseline run** selector populated from the two to four succeeded runs already selected. Start with the first selected run when the comparison has no valid pin. Put the pinned run first in the metrics table, label it **Baseline**, and preserve the relative order of the other columns. Keep the actual metric in every cell. Show a signed delta below each comparable candidate value and use a dash with an accessible label in the baseline's delta position. Distinguish the pinned chart series in the legend and by line style if the overlay is available. The pinned run and the individual run's buy-and-hold reference have distinct labels.

Calculate each delta as **candidate minus pinned baseline** from full-run metrics, using raw values before rounding. Include deltas for the four primary metrics and the current expanded metrics.

| Metrics | Display |
| --- | --- |
| Total return, max drawdown, CAGR, win rate | Signed percentage points. A return of 12% versus 10% gives `+2.00 pp`. A max drawdown of 8% versus 10% gives `−2.00 pp`, a smaller drawdown. |
| Final equity | Signed difference in the shared quote currency, when starting capital also matches. A difference of 50 USDT displays as `+50.00 USDT`. |
| Closed trades | Signed integer difference. A count of 14 versus 11 gives `+3`. |
| Sharpe, profit factor | Signed difference in metric units. Sharpe of 1.10 versus 0.85 gives `+0.25`. |

Keep raw values visible where a delta is unavailable. Pairwise deltas require matching full-run bounds and compatible market, quote currency, timeframe, calendar, and semantics version. Show a plain-language reason where a missing or non-finite value, mismatched window, or incompatible input prevents a delta. Different starting capital suppresses only the final equity delta. Differences in fees, slippage, dataset fingerprint, or benchmark entry are disclosed and can be intentional research variations. Apply these rules per candidate, so a third run does not hide a valid delta for the first pair. An exact overlap can still be plotted when the full-run windows differ. Keep signs and units visible and let the user interpret whether a change is desirable.

## Visual specification

Default to graphite dark and retain a light option in the workspace header. Use Inter for interface text and IBM Plex Mono for code, identifiers, timestamps, and tabular values. Start at 13–14 px for interface text, 14–15 px for source, 16–18 px for work titles, and 11–12 px for plot axes where legibility permits. Use an 8 px spacing rhythm with 4 px increments for compact controls. Start with 34–36 px table rows and toolbar controls, with larger hit areas where touch or reflow demands it. Inline targets must meet the applicable minimum target-size and spacing rules. Use flat pane surfaces, one-pixel dividers, and restrained corner radius.

| Token role | Graphite starting point | Light starting point |
| --- | --- | --- |
| Shell, canvas, inspector | `#11161C`, `#171D24`, `#1C2530` | `#F3F6F7`, `#FFFFFF`, `#F3F7F6` |
| Primary text, secondary text | `#E5EDF3`, `#A5B4C1` | `#172D39`, `#506572` |
| Accent and focus | `#5AD6C4`, `#7DB9FF` | `#087269`, `#14618B` |
| Subtle dividers | `#344150` | `#D5E1E5` |

These values are seeds for theme testing. Choose semantic tokens for positive, negative, warning, focus, selection, unavailable, and chart series. Define foreground/background pairs for actions, rows, and CodeMirror syntax. Check text and control contrast where they appear. Use text, signs, shapes, or line style with color. Keep focus outlines visible, motion restrained, and native inputs legible in both themes. [Accessibility and visual gates](04-verification-and-release.md)
