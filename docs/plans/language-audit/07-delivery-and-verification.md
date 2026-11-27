# Implementation sequence and release verification

Use this page to schedule the plan, check each work package, and preserve the evidence needed to replay older runs. The acceptance criteria in each work package define its feature-level tests.

## Implementation progress

| Delivered | Verification |
| --- | --- |
| Python and browser integration tests use separate loopback endpoints and temporary libraries. The readiness handshake checks the supervisor process, data root, and HTTP instance. | The decoy regression checks an occupied port, and the lifecycle cases exercise simultaneous services and restart. The production browser launch and all 12 Playwright cases passed against their own API. [Supervisor regression](../../../tests/test_supervisor.py) · [Browser test stack](../../../apps/web/tests/local-stack.ts) |
| Text validation and explanation print warnings and suggestions. Indicator and window errors use source terminology, exact spans, signatures, and data bounds. | CLI output and JSON envelope cases pass. The compiler verifies casing and selector suggestions, a byte-order mark, and CRLF coordinates. Preparation tests cover the window ending before warmup and at the first eligible close. [CLI cases](../../../tests/test_contracts.py) · [Compiler cases](../../../tests/conformance/test_compiler_contract.py) · [Runtime cases](../../../tests/conformance/test_runtime_boundaries.py) |
| The engine scopes missing-bar warnings to the execution interval. Bundles report pre-window and execution gap counts. Unrepresentable optional metrics report a numeric range reason. | Publication cases inspect out-of-window gaps, in-window gaps, and the extreme-price Sharpe probe. The source suite passed 819 cases, including the pinned registry and golden execution cases. [Runtime cases](../../../tests/conformance/test_runtime_boundaries.py) |
| Succeeded runs record per-candle rule outcomes and expose sample-aware inspection in the browser and local API. A versioned Parquet file stores observed-bar evidence. The logical ledger digest stays compatible, and saved outcomes remain readable when the original runtime is unavailable. | 822 Python tests and 12 Playwright tests passed. Regressions cover shifts, aliases, gap crossings, empty Volume Profile windows, false and blocked rules, rejected budgets, runtime mismatch, legacy artifacts, and bounds on trace size. [Samples](../../../tests/test_decision_samples.py) · [API lifecycle](../../../tests/test_local_backtests.py) · [Browser flow](../../../apps/web/tests/research.spec.ts) |
| Dataset-aware CLI and HTTP preparation estimate workload. Submission rejects runs whose required resident arrays alone exceed the 1 GiB worker cap. The estimate is available in the editor, run details, and manifest. | 825 Python tests and 12 Playwright tests passed, including preflight parity, cache reuse, paired data, and rejection before enqueueing. A 489,600-candle run with 128 two-operation bindings was admitted at 1,069,776,089 of 1,073,741,824 bytes and succeeded under the supervised worker. [Workload tests](../../../tests/test_workload.py) · [Benchmark evidence](#workload-benchmark) |
| DSL 2 and typed strategy schema 2 support static periods, typed parameters, named records, Boolean lookbacks, and explicit fallback. Execution semantics 2.0.0 use reachable readiness and auxiliary inputs. The CLI and browser submit overrides, and the bundle records them for replay. | The worktree based on `2817366` passed 855 Python tests from source, 855 from a wheel installed with locked dependencies, and 13 isolated Playwright tests. The MACD fixture matches the DSL 1 inline crossing and fills at 21 USDT. A worker run replays from its saved bundle with matching fingerprint and result digest. The browser test changes a period, price, and Boolean value and runs with an unused profile declaration. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 2 cases](../../../tests/test_language_v2.py) · [Worker replay](../../../tests/test_local_backtests.py) · [Browser checks](../../../apps/web/tests/research.spec.ts) |
| Draft checking collects up to eight independent errors. The editor uses recovered record fields, identifies argument roles and bounds, and offers exact-span fixes. Draft checks and dataset-aware validation track the source and inputs of each request. | The worktree based on `2817366` passed 859 source tests, 859 installed-wheel tests, and 16 isolated Playwright tests. Tests cover blocked dependencies, byte-order marks and CRLF, record aliases and nested expressions, keyboard fixes, and obsolete responses. In 1,000 edited-draft probes, draft validity and spec matched strict validation and reported fix spans matched the source bytes. Type checking, production build, strict docs, Ruff, and mypy passed. [Draft API cases](../../../tests/test_api.py) · [Editor workflow cases](../../../apps/web/tests/research.spec.ts) |
| Run settings resolve source defaults, saved presets, and one-run overrides. Presets have stable IDs and revision checks. The worker and candle inspector use the resolved snapshot, and the bundle includes a portable replay configuration. | The worktree based on `2817366` passed 860 Python tests from source and from the installed wheel and 17 isolated Playwright tests. The queued run kept its original settings after a preset update. Equivalent CLI settings matched HTTP validation, and CLI replay reproduced the fingerprint and result digest. The browser duplicated a preset and changed only the period on the same source revision and dataset. Type checking, production build, strict docs, Ruff, and mypy passed. [Queue and replay](../../../tests/test_local_backtests.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| Save and run checks the captured source and inputs, saves the exact draft, and submits the acknowledged revision. An interrupted submission can retry the same revision and inputs from the editor. | All 20 isolated Playwright tests passed. The combined action preserved a captured fee, dataset, and revision through changes made during validation and save. A worker rejection followed by a lost success response produced one run and one saved revision. A stale save precondition preserved the draft and submitted zero runs. [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| Compare computes the `common_start_hold_v1` reference and rebased strategy returns for compatible groups. The policy marks carried positions at the common open and reports explicit reasons for incompatible pairs. | On the worktree based on `2817366`, 861 Python tests passed from source and from the installed wheel. The supported pair stayed visible alongside runs using different data or costs. The hand-calculated fixture checked the common opening price, fee, marked holdings, and excess returns. All 21 isolated Playwright tests passed, including the MACD workflow through explanation, selected-bar inspection, a 21 USDT fill, comparison, and CLI replay from the exact bundle. A four-run probe over 200,000 recorded candles produced 332 sampled points in 0.042 seconds, with 230.3 MiB process peak RSS. [API cases](../../../tests/test_local_backtests.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| DSL 3 binds one same-market higher-timeframe feed and aligns completed secondary closes onto primary rules. Run details, comparison, and bar inspection expose the alignment evidence. Manifest schema 4 preserves the feed input and settings for replay. | On the worktree based on `2817366`, 868 Python tests passed from source and from the installed wheel. The one-hour and four-hour fixture checks native and primary offsets, gaps, staleness, and causal prefixes through fills and equity. All 22 isolated Playwright tests passed. The focused feed scenario also verified both exact-bundle and equivalent CSV replay with matching fingerprints and digests, plus side-by-side alignment settings. The Volume Profile replay test passed. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 3 reference](../../language-v3.md) · [Alignment tests](../../../tests/test_named_feeds.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| DSL 4 sizes a long by its modeled loss at a stop touch. Fill evidence records prices, costs, limits, downward rounding, and the binding constraint. Parameter-only overrides now produce the portable replay file. | On the worktree based on `2817366`, 887 Python tests passed from source and from the installed wheel. The fixture reconciles a 20 USDT stop-touch loss with fees and slippage. Tests cover percentage and ATR stops, allocation and cash limits, float rounding, invalid proposals, an entry-open stop, a later gap, and unchanged legacy fills. All 23 isolated Playwright tests passed. A 150 USDT allocation cap bought about 1.47044407 units, and the browser bundle replayed through the CLI with matching hashes. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 4 reference](../../language-v4.md) · [Sizing tests](../../../tests/test_stop_sizing.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| DSL 5 checks named market and time exits in source order, activates a higher trailing stop at the next open, and can expire a queued signal across a gap. Decision file schema 2 records completed holding candles for per-rule inspection. | On the worktree based on `2817366`, 908 Python tests passed from source and from the installed wheel. The profit rule won the tie and filled at 122 USDT. The timer override filled at 114 USDT on the next open. Coverage includes unavailable predicates and trails, monotonic triggers, gap protection before expiry, stop priority on dual touches, and a final-candle timer. All 24 isolated Playwright tests passed, including browser inspection and CLI replay with matching hashes. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 5 reference](../../language-v5.md) · [Exit tests](../../../tests/test_ordered_exits.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| DSL 6 supports partial exits by fraction or units and adds from available cash. An optional quantity step rounds purchases and partial sales. The fill ledger records weighted-average basis, fee allocation, and realized profit for open and closed cycles. | On the worktree based on `2817366`, 923 Python tests passed from source and from the installed wheel. The two trims left 4.5 units with 450 USDT gross basis, 4.50 USDT entry fees, and a final mark of 2,086.20 USDT. The five-fill cycle closed at 2,101.225 USDT and reconciled 26.275 USDT in fees. Coverage includes same-candle protection after a trim, open protection before an add, rounding, and tiny residuals. All 25 isolated Playwright tests passed, including both ledger views and replay with matching hashes. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 6 reference](../../language-v6.md) · [Ledger tests](../../../tests/test_position_ledger.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| DSL 7 supports replayable exchange sessions and split-adjusted reference units. Metadata schema 2 carries the recorded schedule and splits, and decision file schema 3 preserves actual candle closes and share factors. | On the worktree based on `2817366`, 931 Python tests passed from source and from the installed wheel. The holiday fixture fills on November 29 at 14:30 UTC, marks that shortened session at 18:00 UTC, and counts zero missing candles. A synthetic two-for-one split preserves the opening value of the held position and the sale leaves 1,200 USD. Tests cover daylight-saving changes, missing scheduled observations, actual order age, VWAP resets, and feed and profile alignment. All 26 isolated Playwright tests passed, including metadata import, candle inspection, common-start comparison, and CLI replay with matching hashes. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 7 reference](../../language-v7.md) · [Session tests](../../../tests/test_exchange_sessions.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| DSL 8 supports a borrowed-asset short with signed exposure, reserved proceeds and initial margin, elapsed-time borrow, partial covers, and maintenance liquidation. Position ledger schema 2 records short fill accounting. | On the worktree based on `2817366`, 950 Python tests passed from source and from the installed wheel. The five-unit short reserves 750 USD, pays 9.50 USD of fill fees and 5 USD of borrow, and finishes at 1,035.50 USD. Gapping through the stop leaves 858.75 USD. A maintenance gap can leave a 126 USD deficit. Coverage includes signed positions, partial covers, trails, intrabar and close liquidation, adverse slippage, and exchange closures and splits. All 27 isolated Playwright tests passed, including the short ledger and exact CLI replay. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 8 reference](../../language-v8.md) · [Short tests](../../../tests/test_short_margin.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |
| DSL 9 portfolio execution is available through the CLI. The shared clock settles completed candles and open reductions before entries, and core output includes portfolio equity, per-asset marks, and per-asset decisions. The editor validates and explains portfolio source. | On the worktree based on `2817366`, 958 Python tests passed from source and from the installed wheel. Declaration priority produced 1,150 USD with Alpha first and 850 USD with Beta first. An intervening order could spend a protective exit's proceeds only after the containing candle closed. Tests cover shared reductions, short reserves, position limits, exchange closures, ordered bindings, and replay identity. All 28 isolated Playwright tests passed, including portfolio source explanation. Type checking, production build, strict docs, Ruff, and mypy passed. [DSL 9 reference](../../language-v9.md) · [Portfolio tests](../../../tests/test_portfolio.py) · [Browser workflow](../../../apps/web/tests/research.spec.ts) |

C7 supports portfolio submission through the local API and supervised worker. A queued run preserved the selected asset revisions after an edit, returned Beta's insufficient-cash decision through asset-specific inspection, and replayed through the CLI with matching hashes. The browser selects asset strategies, datasets, optional profile candles, named feeds, dates, costs, and parameter overrides. It displays shared equity, per-asset marks, selected-candle decisions, and paged trades and events. A browser test ran the reference portfolio to 1,150 USD, inspected Beta's rejection, compared two portfolio runs, and replayed a Beta fee override with matching hashes. The single-market common-start reference reports portfolio pairs as unavailable. On the worktree based on `2817366`, 959 tests passed from source and the installed wheel, and 29 browser tests passed. A subsequent named-feed portfolio fixture verified causal fills and replay. Strict documentation, Ruff, mypy, browser type checking, and the production build passed. [Portfolio tests](../../../tests/test_portfolio.py) · [Final workload rerun](#final-portfolio-workload-rerun)

## Isolate integration tests

The audit's initial run encountered an existing preview on port 8000. The test's health check accepted it before the test process reported a bind failure. Two fixture strategies and two fixture runs were created in the preview. A separate-port rerun verified the application tests, and the Git-backed parity case passed in the original checkout. [Python test harness](../../../tests/test_supervisor.py) · [Browser test server configuration](../../../apps/web/playwright.config.ts)

1. Give Python and browser integration tests a fresh data root and test-owned loopback endpoints. Prefer child-owned port allocation or a launcher that retains the socket until the child takes ownership. Thread the resolved API endpoint through the frontend proxy and test client. Keep production loopback defaults and host/origin protections.
2. Require a readiness handshake that proves the child owns the endpoint and expected library before any fixture write. Use a test-instance nonce or an equivalent child-bound handshake. Validate process health and identity across restart scenarios. Stop only processes started by the test.
3. Create a regression with a decoy healthy server on the default address and verify zero requests that mutate it. Exercise startup failure, parallel test instances, temporary-library cleanup, and browser routing to the right API. Document the isolated test launch procedure.

## Merge evidence

For each work item, record the revision tested, the verification commands and results, and the fixture that demonstrates acceptance. For affected bundles, record which artifact and semantics versions the test covers. Add the evidence under [Implementation progress](#implementation-progress) and update the [implementation checklist](08-implementation-checklist.md).

## Version and replay gates

Use the repository's independent version markers for source syntax, typed strategy schema, execution semantics, artifact shapes, and inspection and API envelopes. Decide which contracts change before implementation, then test the selected path at compile, submission, execution, and readback. [Existing version contract](../../results.md#compare-and-replay-runs) · [Contribution rules](../../../CONTRIBUTING.md)

| Change | Compatibility decision to record |
| --- | --- |
| CLI wording or new presentation of existing warnings | Preserve stable diagnostic codes, JSON envelope, and exit status. If the logical diagnostic content changes, check its impact on the result digest. |
| Traces, decision counts, gap diagnostics, or metric availability | Version the affected payload and result digest semantics where needed. Read older artifacts with their original shapes and record which values or warnings differ for new runs. |
| Accepted syntax, parameters, records, Boolean history, and fallback | Review source parsing, inferred types, typed schema, and editor catalogue together. Select the legacy compiler path for v1 and preserve its normalized projection. |
| Reachable warmup, order rules, and accounting | Pin behavior through an explicit semantic version. Keep original v1 readiness, orders, and ledger replay available. |
| Effective overrides and named feeds | Version canonical configuration and input signatures. Include semantic input hashes, effective values, and alignment policy. Keep raw input provenance in the bundle inventory. |
| Portfolio source and execution | Use typed schema 9, semantics 9.0.0, and artifact schema 5. Fingerprint the ordered asset bindings and each asset's effective execution configuration and data. Preserve per-asset decision files and the globally ordered event sequence. |

For each release, verify that the reader opens the original single-input and Volume Profile artifacts. Use the pinned runtime and dependency inventory to compare historical fingerprints and digests. When a current build changes only the environment identity, verify the applicable logical results separately. Keep published historical bundles intact and deploy new readers alongside the versions they support.

## Workload benchmark

The baseline is the worktree before workload preflight. Baseline and candidate ran separately on the same arm64 macOS host with Python 3.12.16 and NumPy 2.5.5. Each measured workload used three repetitions after a warmup run and the same 14,400 primary candles. The dense profile workload also used 28,800 child candles. [Benchmark harness](../../../scripts/benchmark_indicators.py)

Run the harness on each revision with the same options. This invocation measures the wide indicator workload.

```sh
uv run --locked --extra api python scripts/benchmark_indicators.py \
  --workload wide --rows 14400 --period 128 --repeats 3 --publish
```

The table shows baseline → candidate. Times are median milliseconds. Execution includes expression evaluation, and publication includes preparation, execution, and artifact writing. Peak memory is the process RSS high-water mark across the benchmark.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed | 1.88 → 1.75 | 0.04 → 0.09 | 159.26 → 158.97 | 199.06 → 200.18 | 932.44 → 932.50 | 134.06 → 124.55 | 0 |
| Wide, period 128 | 0.78 → 0.84 | 0.03 → 0.08 | 8.67 → 8.58 | 49.06 → 49.19 | 765.09 → 760.89 | 130.88 → 131.03 | 0 |
| Dense profile | 0.72 → 0.77 | 23.15 → 23.97 | 382.42 → 372.52 | 416.14 → 412.12 | 1,145.69 → 1,168.31 | 135.08 → 134.77 | 0 |
| Event-heavy | 0.64 → 0.63 | 0.03 → 0.07 | 0.47 → 0.46 | 425.43 → 433.86 | 8,164.15 → 8,197.06 | 269.19 → 258.25 | 33,600 |

Candidate execution throughput was 71,934, 292,732, 34,941, and 33,190 primary candles per second, respectively. The event-heavy fixture closed 4,800 trades and wrote a 52.71 MB bundle. Its estimated event ceiling was 115,200 events. Advisory event storage can exceed the observed footprint when predicates rarely fire.

### DSL 3 workload rerun

The same host and locked Python and NumPy versions ran the preflight baseline and the worktree with named feeds. Each used 14,400 primary candles and the same three measured repetitions. The table shows baseline → DSL 3 worktree, with times in median milliseconds.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mixed | 1.69 → 1.79 | 0.03 → 0.10 | 154.02 → 153.36 | 197.01 → 194.59 | 906.87 → 914.74 | 131.36 → 132.20 | 0 |
| Wide, period 128 | 0.74 → 0.87 | 0.03 → 0.07 | 8.15 → 8.20 | 48.17 → 49.42 | 743.63 → 758.77 | 129.66 → 136.91 | 0 |
| Dense profile | 0.71 → 0.74 | 22.08 → 22.35 | 362.43 → 370.49 | 405.96 → 411.50 | 1,136.66 → 1,128.84 | 132.50 → 135.31 | 0 |
| Event-heavy | 0.57 → 0.63 | 0.03 → 0.07 | 0.42 → 0.43 | 417.01 → 442.53 | 8,074.33 → 8,068.38 | 257.52 → 268.22 | 33,600 |

A named-feed probe aligned a 20-period four-minute EMA with 14,400 one-minute candles. The 3,600 native rows produced zero trade events. Median compile, prepare, evaluate, execute, and publish times were 0.64, 0.23, 2.25, 43.33, and 740.59 milliseconds. Admission estimated 2,620,889 bytes of required resident arrays, and the process peaked at 121.83 MiB RSS.

### DSL 4 workload rerun

The same host reran the four workloads with stop sizing implemented. The table shows the DSL 3 worktree → DSL 4 worktree, with times in median milliseconds. The workload strategies use their existing sizing forms.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mixed | 1.79 → 1.81 | 0.10 → 0.09 | 153.36 → 157.83 | 194.59 → 191.97 | 914.74 → 908.69 | 132.20 → 132.94 | 0 |
| Wide, period 128 | 0.87 → 0.74 | 0.07 → 0.06 | 8.20 → 8.10 | 49.42 → 48.39 | 758.77 → 753.64 | 136.91 → 119.05 | 0 |
| Dense profile | 0.74 → 0.75 | 22.35 → 22.67 | 370.49 → 366.44 | 411.50 → 396.66 | 1,128.84 → 1,133.81 | 135.31 → 134.33 | 0 |
| Event-heavy | 0.63 → 0.59 | 0.07 → 0.07 | 0.43 → 0.43 | 442.53 → 426.93 | 8,068.38 → 8,053.37 | 268.22 → 270.52 | 33,600 |

An additional DSL 4 probe compared allocating 10% of equity with risking 1% against a 10% stop. Both ran the same 14,400 one-minute candles with zero costs, an entry when close exceeded 1, and a signal exit when close exceeded 100.5. Each recorded 4,800 trades and 33,600 events. The two runs ended at 115,607.17 USDT to displayed precision. Across three measured repetitions, execution was 299.82 → 322.95 ms and publication was 5,994.03 → 6,627.55 ms. Peak RSS was 224.88 → 231.12 MiB, and the extra sizing evidence increased bundle size from 37.46 to 43.29 MB.

### DSL 5 workload rerun

The same host reran the established workloads. The table shows the DSL 4 worktree → DSL 5 worktree, with times in median milliseconds. These strategies use their existing single exit.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Mixed | 1.81 → 1.83 | 0.09 → 0.10 | 157.83 → 152.91 | 191.97 → 192.45 | 908.69 → 927.59 | 132.94 → 122.20 | 0 |
| Wide, period 128 | 0.74 → 0.78 | 0.06 → 0.07 | 8.10 → 8.18 | 48.39 → 50.74 | 753.64 → 742.61 | 119.05 → 123.70 | 0 |
| Dense profile | 0.75 → 0.76 | 22.67 → 23.17 | 366.44 → 365.82 | 396.66 → 401.15 | 1,133.81 → 1,135.01 | 134.33 → 136.47 | 0 |
| Event-heavy | 0.59 → 0.61 | 0.07 → 0.07 | 0.43 → 0.43 | 426.93 → 437.74 | 8,053.37 → 8,104.57 | 270.52 → 268.53 | 33,600 |

A focused 14,400-candle probe kept the entry and market exit threshold fixed and added ordered rules, a three-candle timer, and a five-unit price trail. Both variants closed the same 4,800 trades with equal final equity. The ordered run recorded 9,600 trail events, increasing the event count from 33,600 to 43,200. Across three measured repetitions, execution was 297.25 → 385.52 ms and publication was 5,994.15 → 7,869.03 ms. Peak RSS was 225.67 → 255.38 MiB and bundle size was 37.20 → 48.91 MB.

### DSL 6 workload rerun

The same host reran the established workloads. The table shows the earlier DSL 5 measurements → the DSL 6 worktree, with times in median milliseconds. These four strategies use their existing order forms.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed | 1.83 → 1.93 | 0.10 → 0.12 | 152.91 → 168.15 | 192.45 → 214.38 | 927.59 → 962.00 | 122.20 → 135.56 | 0 |
| Wide, period 128 | 0.78 → 0.92 | 0.06 → 0.09 | 8.18 → 8.76 | 50.74 → 51.55 | 742.61 → 914.98 | 123.70 → 119.66 | 0 |
| Dense profile | 0.76 → 0.92 | 23.17 → 24.11 | 365.82 → 376.61 | 401.15 → 406.34 | 1,135.01 → 1,160.78 | 136.47 → 136.33 | 0 |
| Event-heavy | 0.61 → 0.74 | 0.07 → 0.08 | 0.43 → 0.48 | 437.74 → 525.66 | 8,104.57 → 10,580.41 | 268.53 → 249.08 | 33,600 |

A back-to-back event-heavy rerun used the DSL 5 package extracted from its verified wheel and the DSL 6 source with the same runtime. Execution measured 477.90 → 445.00 ms and publication measured 8,345.58 → 8,032.83 ms. Both produced 33,600 events.

A separate probe repeated the six-candle position fixture over 14,400 one-minute candles. With only the initial buy and final sale, 2,400 cycles produced 4,800 fills and 14,400 events. Adding the two trims and a cash-funded add produced 12,000 fills and 36,000 events across the same number of cycles. Execution took 199.00 → 556.53 ms and publication took 3,484.84 → 7,529.78 ms across three measured repetitions. Peak RSS was 177.09 → 238.75 MiB, and the bundle size was 19.33 → 43.79 MB.

### DSL 7 workload rerun

Each pair used the verified DSL 6 wheel and the DSL 7 source back to back on the same host with the same Python and dependencies. The table shows DSL 6 → DSL 7, with median milliseconds across three repetitions. These workloads use the continuous calendar and each pair produced the same event and trade counts.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed | 1.98 → 2.00 | 0.11 → 0.11 | 166.74 → 175.78 | 212.03 → 222.22 | 996.46 → 1,005.57 | 139.06 → 134.48 | 0 |
| Wide, period 128 | 0.90 → 0.97 | 0.08 → 0.09 | 9.06 → 8.75 | 53.70 → 53.91 | 803.57 → 859.40 | 134.48 → 132.44 | 0 |
| Dense profile | 0.97 → 0.76 | 24.87 → 22.67 | 390.67 → 371.02 | 419.54 → 403.89 | 1,300.22 → 1,135.62 | 136.80 → 135.45 | 0 |
| Event-heavy | 0.66 → 0.68 | 0.08 → 0.09 | 0.44 → 0.45 | 478.55 → 449.46 | 8,975.74 → 7,992.36 | 269.55 → 255.75 | 33,600 |

A focused DSL 7 probe compared a continuous raw spot series with 40 recorded six-hour sessions and one synthetic two-for-one split. Both used 14,400 one-minute candles, zero events, and final equity of 1,000 USD. Import took 1.96 → 3.04 ms, execution took 43.10 → 41.55 ms, and publication took 748.40 → 747.55 ms. The minimum resident array estimate rose from 2,203,289 to 3,355,289 bytes and peak RSS rose from 130.47 to 136.80 MiB.

### DSL 8 workload rerun

Each pair used the verified DSL 7 wheel and the DSL 8 source back to back on the same host and dependencies. Times are median milliseconds over three repetitions. The four established workloads use their existing long order forms and the continuous calendar. Both versions produced the same trade and event counts within each pair.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed | 1.96 → 2.27 | 0.13 → 0.13 | 166.12 → 165.67 | 211.90 → 210.19 | 997.53 → 984.82 | 138.22 → 133.94 | 0 |
| Wide, period 128 | 0.87 → 0.92 | 0.09 → 0.09 | 9.45 → 9.28 | 54.13 → 53.54 | 835.50 → 809.61 | 121.81 → 128.12 | 0 |
| Dense profile | 0.95 → 0.94 | 24.43 → 24.55 | 398.19 → 385.79 | 430.31 → 429.16 | 1,225.33 → 1,186.01 | 136.08 → 136.45 | 0 |
| Event-heavy | 0.93 → 0.71 | 0.12 → 0.10 | 0.69 → 0.49 | 597.12 → 486.62 | 9,035.18 → 8,556.05 | 270.94 → 257.28 | 33,600 |

A focused DSL 8 probe ran 4,800 round trips with the same 14,400 one-minute candles and 500 USD of entry notional per trade. The long run ended at 1,000 USD. The short incurred 16.67 USD of borrow and ended at 983.33 USD. From long to short, events rose from 28,800 to 33,600, execution took 354.89 → 421.11 ms, publication took 5,937.08 → 6,994.22 ms, and peak RSS rose from 213.27 to 239.64 MiB. Bundle size rose from 29.38 to 38.20 MB.

### DSL 9 execution workload checkpoint

The verified DSL 8 wheel and the DSL 9 execution worktree ran back to back on the same host and dependencies. These workloads use their existing single-market strategies and continuous clocks. Each pair produced the same trade and event counts. Times are median milliseconds over three repetitions.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed | 1.93 → 1.82 | 0.12 → 0.10 | 155.27 → 153.12 | 197.72 → 201.34 | 919.65 → 904.73 | 139.66 → 126.56 | 0 |
| Wide, period 128 | 0.81 → 0.76 | 0.07 → 0.07 | 8.18 → 8.21 | 50.87 → 49.61 | 747.10 → 748.59 | 132.48 → 134.64 | 0 |
| Dense profile | 0.77 → 0.74 | 22.51 → 22.37 | 364.51 → 364.74 | 404.54 → 403.16 | 1,129.49 → 1,143.33 | 137.52 → 130.11 | 0 |
| Event-heavy | 0.60 → 0.61 | 0.07 → 0.07 | 0.44 → 0.44 | 443.29 → 440.16 | 8,132.37 → 8,132.48 | 267.34 → 254.11 | 33,600 |

A portfolio probe used 7,200 one-minute candles per asset. In 2,400 cycles, Alpha took the shared entry and Beta's fixed cash request was rejected. The run produced 2,400 round trips, 21,600 events, 7,202 portfolio equity points, and 14,402 asset marks. Final equity was 1,000 USD. Median execution and publication took 390.13 and 4,173.21 ms, respectively. Required resident storage was estimated at 59,904,000 bytes, peak RSS was 198.59 MiB, and the bundle was 38.64 MB.

### Final portfolio workload rerun

The same host ran the verified DSL 8 wheel and current source back to back with three measured repetitions. The established single-market workloads retain identical trade and event counts. Times are median milliseconds.

| Workload | Compile | Prepare | Evaluate | Execute | Publish | Peak MiB | Events |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Mixed | 1.97 → 2.09 | 0.12 → 0.11 | 157.10 → 161.88 | 198.01 → 207.01 | 1,512.53 → 996.96 | 138.59 → 126.73 | 0 |
| Wide | 0.86 → 0.88 | 0.09 → 0.09 | 8.62 → 8.38 | 51.32 → 51.16 | 769.71 → 766.07 | 134.69 → 132.64 | 0 |
| Dense profile | 0.88 → 0.77 | 23.91 → 23.88 | 374.18 → 370.63 | 414.67 → 411.78 | 1,179.16 → 1,162.43 | 135.31 → 140.34 | 0 |
| Event-heavy | 0.83 → 0.63 | 0.10 → 0.08 | 0.44 → 0.49 | 472.24 → 476.65 | 8,882.07 → 8,163.80 | 267.45 → 257.53 | 33,600 |

The two-asset probe repeated 7,200 candles per asset and produced 2,400 closed trades and 21,600 events. Median execution and publication took 426.25 and 4,215.57 ms. The minimum resident estimate was 59,904,000 bytes, peak RSS was 198.84 MiB, and the bundle was 38.64 MB. Final equity remained 1,000 USD.

## Reference scenario

Build a small synthetic daily fixture and run the full author workflow when its dependencies are available.

1. Save a strategy with typed MACD periods, one named MACD record, and a trend condition that uses the previous bar. Compare it with an equivalent inline crossing using fixed literals.
2. Use Explain to identify the selected fields that drive readiness. Add an unused longer indicator and show the versioned readiness behavior.
3. Inspect a false bar, an unavailable prior sample, the signal close, and the subsequent fill. Verify the sample values and event sequence by hand.
4. Run a variant with one period changed through the browser, then through the CLI with the same resolved values. Confirm exact source and input identity, the intended configuration difference, and equivalent logical results under the same version and runtime.
5. Compare the two variants with the common-start reference and replay a run from its saved bundle. Open the historical three-candle ledger and verify its **110 USDT** buy, **120 USDT** sell, and **1,090.91 USDT** final equity. [Golden example](../../quickstart.md#simulate-and-check-the-fills)

## Release checks

- Run relevant clause-indexed conformance, property, fuzz, golden execution, registry parity, and identity cases. Run the full source and installed-wheel suites for a release. Include early end-of-window, allowed gap, unavailable data, and binary64 extremes in targeted regressions. Document changes to golden outputs with their semantic version. [CI checks](../../../.github/workflows/test.yml)
- Verify the CLI, direct HTTP API, supervised worker, and browser agree on source spans, effective configuration, terminal results, and artifacts. Run browser type checking and the production build against a clean lockfile install, then Playwright against the isolated service. The audit's local duplicate ambient type directories are a reason to verify from a clean install. [Browser scripts](../../../apps/web/package.json) · [Browser acceptance](../research-terminal/04-verification-and-release.md)
- Regenerate OpenAPI and editor metadata when contracts change. Update the packaged and reference grammar and schema together. Update the relevant specification, CLI, API, browser help, example, and changelog in the same public change. Run the strict docs build. [Generated contracts](../../../scripts/web_contracts.py) · [Contribution checks](../../../CONTRIBUTING.md)
- Record same-machine baseline and candidate performance for representative, wide, profile, and event-heavy runs. Include compile, prepare, evaluate, execute, publish, peak memory, and event volume where measurable. Review admission estimates and actual results against enforced worker limits. [Benchmark harness](../../../scripts/benchmark_indicators.py)

## Completion audit

The implementation checklist maps each work package to its design and acceptance criteria. The following evidence was checked against the current worktree based on `2817366`.

| Scope | Evidence |
| --- | --- |
| A1–A6, diagnostics, decision evidence, finite metrics, and admission | The isolation, compiler, runtime boundary, decision sample, and workload cases cover the specified handoffs and failure paths. The recorded near-limit worker run and current full suites cover admission and publication. [Supervisor](../../../tests/test_supervisor.py) · [Decision samples](../../../tests/test_decision_samples.py) · [Runtime boundaries](../../../tests/conformance/test_runtime_boundaries.py) · [Workload](../../../tests/test_workload.py) |
| B1–B4, typed composition and reachable readiness | Named MACD and inline crossings, record fields, Boolean history, fallback, causal prefixes, and scale diagnostics have direct cases. The complete suite includes v1 golden and registry cases. [DSL 2 cases](../../../tests/test_language_v2.py) · [Goldens](../../../tests/test_golden.py) · [Registry parity](../../../tests/test_registry_parity.py) |
| B5–B8, author workflow and comparison | Queue snapshots, preset changes, exact revision submission, retries, keyboard editor actions, and common-start compatible pairs are exercised by the worker and browser scenarios. The MACD workflow records selected-bar inspection and CLI replay. [Worker lifecycle](../../../tests/test_local_backtests.py) · [Browser scenarios](../../../apps/web/tests/research.spec.ts) |
| C1–C4, feeds and long execution | Cases cover completed native feed closes, gaps, staleness and causal prefixes, stop sizing, ordered exits, trailing protection, partial sales, adds, basis, and legacy fills. [Feeds](../../../tests/test_named_feeds.py) · [Stop sizing](../../../tests/test_stop_sizing.py) · [Ordered exits](../../../tests/test_ordered_exits.py) · [Position accounting](../../../tests/test_position_ledger.py) |
| C5–C7, exchange clocks, shorts, and portfolios | Fixtures reconcile holiday and shortened sessions, daylight-saving changes, splits, short collateral and financing, shared cash priority, independent clocks, per-asset marks, and saved-bundle replay. A separate portfolio feed case checks alignment and input replay. [Sessions](../../../tests/test_exchange_sessions.py) · [Shorts](../../../tests/test_short_margin.py) · [Portfolios](../../../tests/test_portfolio.py) |
| Version, transport, documentation, and workload gates | The complete source and locked-wheel suites each passed 959 cases before the additional named-feed portfolio regression passed separately. The isolated browser suite passed 29 cases. The current grammar and schema copies match, OpenAPI and browser types were regenerated, and strict docs, type checks, production build, and the final workload rerun passed. [Contracts](../../../tests/test_contracts.py) · [API contracts](../../../tests/test_api.py) · [Final workload rerun](#final-portfolio-workload-rerun) |

Portfolio comparisons show recorded full-run curves and metrics. The common-start single-market reference reports portfolio pairs as unavailable. [Portfolio comparison](../../language-v9.md#run-the-shared-cash-example)

### Worktree revalidation

The revalidation checked all 21 implementation items and matched the published grammar and typed schema for DSL 1–9 against the rebuilt wheel. The portfolio example returned 1,150 USD from the installed wheel. Replaying its bundle reproduced the run fingerprint and result digest. [Implementation checklist](08-implementation-checklist.md) · [Portfolio example](../../language-v9.md#run-the-shared-cash-example)

The portfolio editor pins each selected asset revision through validation and submission, including when a newer revision appears in the strategy list. Portfolio result links open the workspace with the run ID, and candle inspection uses the selected asset's dataset index. A portfolio whose combined ledger exceeds the finite numeric range now fails with `E_NUMERIC_EXECUTION` and leaves no published bundle. [Browser regression](../../../apps/web/tests/research.spec.ts) · [Overflow regression](../../../tests/test_portfolio.py)

The worktree based on `2817366` passed 961 Python tests from source and 961 from the wheel installed with locked dependencies. All 29 isolated browser cases passed against that wheel after the clean lockfile install, type check, and production build. The deeper language profile passed 524 cases. Strict MkDocs, Ruff, mypy, and generated OpenAPI, editor catalogue, and TypeScript parity checks passed. All DSL 2–9 reference backtest commands ran from the installed package.

The final wheel processed 14,400 candles across two assets, produced 2,400 trades and 21,600 events, and used 201.52 MiB peak RSS. The test suites ran alongside this probe, so use the earlier controlled rerun for timing comparisons. [Workload baseline and candidate](#final-portfolio-workload-rerun)
