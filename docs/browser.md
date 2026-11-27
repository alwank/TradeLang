# Use the local browser workspace

Use TradeLang in your browser to import candles, write and validate a strategy, run a saved revision, and compare completed backtests. The workspace keeps its library and run artifacts in a local data directory.

## Start the workspace

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Node.js 22 with npm. From a TradeLang checkout, install the locked dependencies and build the web app.

~~~sh
uv sync --locked --extra api
npm ci --prefix apps/web
npm --prefix apps/web run build
uv run --locked --extra api tradelang-local --data-root runs/local-library --web apps/web
~~~

Open [TradeLang on your computer](http://127.0.0.1:3000/). The start page opens **Strategies**. Use the numeric loopback address so the browser origin matches the API's local configuration. Keep the process running while you use the workspace, and press Ctrl-C in the launch terminal to stop it.

To run a separate workspace, set `--web-port` to an unused browser port and `--api-port` to a different unused port. Use `--api-port 0` to let the supervisor select the API port. Open the numeric loopback address at the browser port you chose.

## Run and inspect an example

Browser starter templates take their market and timeframe from the dataset you select. Choose candles that cover the strategy's date range and match its capital currency. Add `market` or `timeframe` to the source to require a specific value.

1. Open **Datasets** and select **Import dataset**. Choose `docs/fixtures/core.csv` and enter symbol `TESTUSDT`, quote currency `USDT`, and timeframe `1d`. Keep **Reject gaps** selected. After import, check the candle preview and dataset quality. [Candle data requirements](candle-data.md)
2. Open **Strategies**, select **New strategy**, and create a blank draft. Paste the source from `docs/fixtures/core.trade` into **Source** and select the imported dataset.
3. Select **Validate**. Use **Problems** to review diagnostics. Select a line diagnostic to jump to its source span. Use **Explain strategy** and **Assumptions** in the inspector to review how the source and data resolve.
4. Select **Save** to create a revision. When the saved source passes validation with the selected data, select **Run backtest**. **Runs** in the dock shows the acknowledged run while you stay in **Source**.
5. Choose **Open run** in the dock. When the run succeeds, verify final equity of **1,090.91 USDT**. Select **T000001** to inspect the entry at **110 USDT**, the exit at **120 USDT**, and the linked events. **View strategy** opens the executed revision. Use **Download exports** for the full-resolution files. [Results and artifacts](results.md)
6. Choose **Source** to return to your buffer and caret. Use **Backtest** to reopen the result you were inspecting.
7. Create a second draft using the same example. Replace `when true` with `when false`, select the same dataset, save, validate, and run it.
8. Open **Runs**, select the two succeeded runs, and choose **Compare 2 runs**. Choose a **Baseline run** and inspect the signed changes below each full-run metric. The baseline appears in the first data column. Verify that both curves start at index 100 and the second strategy has zero closed trades.

After dataset-aware validation, open **Assumptions** in the strategy editor for the estimated workload and worker memory budget. The estimate also appears in **Run details** on completed runs. [Workload fields](results.md#review-workload)

## Resolve draft errors

After you pause typing, **Problems** shows errors from the latest source. A malformed declaration can also leave dependent rules unchecked. Fix that declaration first to check those rules. Use **Validate** to check the full source with the selected dataset and parameter values before running.

Select a diagnostic to jump to its source. When a diagnostic offers **Apply fix to line**, select the button to replace the indicated text and return focus to the editor. Draft fixes keep the rest of the source bytes intact.

While editing an indicator call, the signature hint shows the active argument and its allowed values. Place the caret after a record's dot to complete a field. Press Ctrl+Space to open completions from the keyboard. Point-scale indicators and fields show their scale in hover help.

## Override strategy parameters

Open a [DSL 2 strategy with parameter declarations](language-v2.md#parameters-and-static-arguments), then select **Run settings**. Enter numeric overrides in the declared units or choose a Boolean value. Clear a numeric entry or choose **Default** for a Boolean to use its preset or source value. Select **Validate** with the dataset before running. Editing source clears the explicit parameter overrides. After completion, open **Run details** to see the effective values that the worker used.

## Reuse a run preset

1. Select the candles in **Dataset** and open **Run settings**.
2. Enter the dates, capital, costs, or parameters you want to reuse. Leave a field blank to take its value from the selected preset or the source.
3. Enter a **Preset name** and select **Save as preset**. To duplicate an experiment, select its preset, edit one value, enter a new name, and select **Save as preset** again.
4. Select **Validate** to check the selected inputs. In **Assumptions**, review the effective settings and first executable open.
5. Run the selected revision. When the run completes, check the preset revision and values in **Run details**. Updating the preset applies to future submissions.

## Save and run a draft

For an edited strategy with a dataset selected, choose **Save and run**. You can also press Cmd+Alt+Enter or Ctrl+Alt+Enter. The action checks the captured source and inputs, saves that source as a revision, and submits the acknowledged revision. Edits you make while it runs stay in the editor for a later submission.

If saving succeeds and submission fails, choose **Retry captured run** to use the recorded revision and inputs. Use **Save** on its own to keep a draft at any stage. When the strategy has a newer saved revision, use the conflict controls to review it before submitting again.

## Inspect a candle

To import [exchange sessions](language-v7.md), choose the candle file and its **Metadata JSON** file in **Import dataset**. The dataset details show its calendar version and price basis.

For a [DSL 8 short](language-v8.md), open **Run details** to see borrow costs, remaining reserve, and any liquidations. The fill ledger shows signed remaining quantity and the borrow cost allocated to each cover.

For a [DSL 9 portfolio](language-v9.md), select a saved strategy revision and dataset for each asset. The selected revision stays pinned if a newer revision becomes available. Expand the asset's additional candles or run settings to supply a profile, named feed, dates, costs, or parameter overrides. The result shows shared equity and asset marks. To inspect a decision, select the asset and enter a zero-based index from its dataset within its execution window.

In a succeeded backtest, select **Inspect a candle** near the equity chart. Enter an observed primary dataset row using the zero-based index and select **Inspect candle**. For a closed trade, select **Inspect entry candle** or **Inspect fill candle** in **Trade details** to jump directly to its evidence.

Read the entry and exit separately. Open the expression samples to check the source line, sample times, and values behind a result. On a buy fill candle, review cash, sizing, and the protection levels established at the open. Saved outcomes and events remain available when the expression samples require a different runtime. Older runs show a notice when no candle inspection was recorded.

For [stop-based sizing](language-v4.md), open **Stop-based sizing** on the fill candle to see the modeled loss, allocation limit, and the constraint that determined the quantity.

For [ordered exits and trailing stops](language-v5.md), use **Ordered exit rules** on a signal candle to see the winning rule and which rules were skipped. Open **Trailing stop changes** to see the old and new triggers and when the new trigger activates.

For [partial exits or adds](language-v6.md), open **Position fill ledger** in a closed trade or open position. Each row lists the quantity, fee, cash after the fill, realized net P&L, and remaining basis.

For a [named higher-timeframe feed](language-v3.md), select its candles in the **Feed** control that carries its name. Validate with both datasets selected. In candle inspection, feed samples show the secondary clock and observed close time. **Run details** and **Compare** show the feed identity and alignment policy.

## Recover a draft and adjust the workspace

The browser caches unsaved source per strategy in the current tab. After a refresh, choose **Restore draft** or **Discard draft**. If the saved revision has changed, review or copy the recovered source before choosing **Use recovered draft**. Use **Save** when you want the restored edits to become a revision.

The header opens in Graphite. Choose **Light** in **Theme** to change it. The browser remembers the theme and pane visibility. On narrow screens, the inspector stacks after the main pane. Tables and source scroll within their own regions.

Open **Shortcuts** on the strategy toolbar to see the editor commands. Press Command on macOS or Control on Windows and Linux.

| Keys | Action |
| --- | --- |
| Command or Control + S | Save the draft |
| Command or Control + Shift + Enter | Validate the current source and data |
| Command or Control + Enter | Submit the saved, validated revision |
| Command or Control + Alt + . | Move focus between source and the dock toggle |

The same buttons and links are available through the regular tab order. Use Left and Right to move between **Problems** and **Runs**, or between **Explain** and **Assumptions**.

## Interpret comparison deltas

A delta subtracts the pinned baseline from the candidate. The chart uses the timestamps shared by the selected runs. A delta uses full-run metrics and requires matching full-run windows and compatible market, currency, timeframe, calendar, and execution semantics. Final equity also requires equal starting capital. **Run inputs** shows recorded differences above the plots. Use **Change runs** to adjust the selection and keep the pin when its run stays selected.

Open **Common-start benchmark** to compare strategies over a shared executable window with the same primary candles and costs. Review the disclosed dates, fees, and slippage, then read **Excess over reference** for the difference in percentage points. If more than one group is eligible, choose one in **Run group**. Pair-specific reasons explain unavailable comparisons. [Benchmark calculation](results.md#compare-a-common-start-benchmark)

## Restore or move a library

Stop TradeLang and back up the entire directory passed to `--data-root`. Keep the SQLite library, imported datasets, and run artifacts together. Restore or move the copy as one directory, then start with its path. Startup applies pending SQLite migrations, so keep a backup before upgrading.

An interrupted or cancelled run keeps its source and input references in **Runs**. Start a new run from the editor to try again. The worker handles one backtest at a time and accepts up to 20 queued runs. Use the CSV, Parquet, and event exports for the full curve and audit trail when the browser shows a sampled chart.
