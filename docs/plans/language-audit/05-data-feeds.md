# Named data feeds and causal alignment

Add one read-only secondary timeframe for the same market. Use a higher-timeframe indicator as the first public example. Draw on the explicit primary and child preparation already used by Volume Profile. [Paired candle contract](../../candle-data.md#pair-candles-for-volume-profile) · [Data preparation](../../../src/tradelang/data.py)

DSL 3 assigns the fixed role `higher_timeframe`. The declaration sets the expected timeframe and maximum age. The `completed_close_v1` policy keeps primary structural warmup and checks secondary readiness at each primary close. [Language reference](../../language-v3.md)

## Feed declarations and runtime binding

1. Define a named feed declaration with expected timeframe and role. Resolve that name to an imported dataset during validation and submission. For the first release, require the same market, currency, calendar, timestamp convention, and price basis as the primary feed. Report mismatches by feed name.
2. Give expressions an explicit evaluation clock. Evaluate an indicator and a native lookback on its declared feed before aligning to the primary clock. On an aligned series, a lookback counts primary observations. Require explicit alignment when combining expressions on different clocks and show it in Explain.
3. At a primary decision close, select the latest eligible secondary value whose candle has closed at or before that decision time. Define tie handling, pre-window history, gaps, and a staleness limit. Return unavailable when coverage or staleness rules fail. Keep fills on the primary feed.
4. Include the feed name, role, resolution policy, candle hashes, and metadata in the run snapshot and manifest. Canonicalize feed ordering and bundle the exact input files for replay. Record the same alignment assumptions in the inspector and Compare.

## Volume Profile compatibility

Keep Volume Profile's complete-child-interval and workload rules for its rolling distribution. Share input selection and metadata validation where the rules match. Maintain the existing paired-input signature and artifact reader for v1 runs. If a later feed declaration can supply the child input, document how it maps to the existing role and version that mapping. [Profile work limits](../../../src/tradelang/functions/profile.py) · [Volume Profile replay](../../results.md#replay-a-volume-profile-run)

## Acceptance

| Fixture | Required result |
| --- | --- |
| A one-hour entry with a four-hour trend | The trend switches at the first primary close that can observe the completed four-hour candle. A partial candle contributes zero samples. |
| Prefix and future perturbation | Appending or changing future secondary rows leaves every earlier aligned value, decision, and fill equal when the earlier admissible inputs are equal. |
| Gap, stale sample, and insufficient history | Each yields the specified unavailable reason. The selected-bar inspector names the feed, clock, source sample, and validity. |
| Lookback before and after alignment | The results differ in the known fixture according to native and primary row counts. Both match their documented semantics. |
| Equivalent input and replay | CLI and browser resolve the same feeds. Equivalent CSV and Parquet inputs preserve normalized identity in the same runtime. Existing v1 single-input and Volume Profile bundles continue to open and replay. |

Ship this stage before independent-symbol signals or multi-asset execution. A future cross-market stage must define per-feed sessions, currencies, stale data limits, and additional identity. [Broader execution stages](06-execution-capabilities.md#additional-markets)
