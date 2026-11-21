# TradeLang indicator expansion

This plan is for TradeLang maintainers implementing the 38 indicator families in the benchmark shortlist. It specifies the public calls, formulas, output units, warmup, and failure behavior proposed for each family. The roadmap packages the work into independently testable changes. The baseline is commit `6da1e38`.

Start with the language and evaluator work in document 01. Implementation order can differ from shortlist rank when a lower-ranked primitive supports several higher-ranked indicators.

| Document | Use it to |
| --- | --- |
| [01. Language and runtime foundation](01-language-and-runtime.md) | Extend the registry, typed AST, kernel context, and release compatibility checks. |
| [02. Core additions, ranks 1–8](02-core-indicators.md) | Implement DMI, Stochastic, VWAP, Supertrend, Donchian, Keltner, Stochastic RSI, and OBV. |
| [03. Standard additions, ranks 9–16](03-standard-indicators.md) | Implement MFI, CCI, Williams %R, SAR, WMA, RMA, VWMA, and CMF. |
| [04. Extended additions, ranks 17–28](04-extended-indicators.md) | Implement trend, range, Bollinger-derived, and volume indicators. |
| [05. Additional additions, ranks 29–36](05-additional-indicators.md) | Implement adaptive smoothing, oscillators, rolling regression, and Chandelier Exit. |
| [06. Zig Zag and Volume Profile, ranks 37–38](06-zigzag-and-volume-profile.md) | Implement causal swing confirmation and lower-timeframe volume aggregation. |
| [07. Verification](07-verification.md) | Build independent oracles, conformance fixtures, replay checks, and benchmarks. |
| [08. Delivery roadmap](08-delivery-roadmap.md) | Sequence pull requests and verify each release. |
| [09. Implementation evidence](09-implementation-evidence.md) | Review the shipped contracts, reference comparisons, and performance measurements. |

## Decisions that shape the implementation

- Keep the ten baseline calls and their results compatible. Use additive v1 calls and the existing field-selection syntax. The proposed public surface has one canonical call name per family, for 48 total built-ins after the final milestone.
- Use completed candles and per-field readiness. Use fractional ratios for relative volatility, Bollinger measures, and volume multiples. Use numeric points for familiar oscillator scales and document that distinction alongside the calls.
- Use UTC opening dates for VWAP and apply it to fixed intraday bars contained within a UTC day. Publish Zig Zag values when a swing is confirmed. Keep Ichimoku displacement as an explicit historical reference in strategy logic.
- Implement Volume Profile last. The first version uses one explicitly supplied, aligned lower-timeframe dataset, a rolling window, and fixed-width price bins. Its volume-at-price model assigns each child bar's volume to its close bin.

Use the existing reference and compatibility corpus for the ten baseline contracts. The external references are formula and behavior benchmarks. Verify matching variants and parameters before claiming numerical parity. [Baseline indicator reference](../../indicators.md), [Existing parity runner](../../../tests/test_registry_parity.py), [TA-Lib functions](https://ta-lib.org/functions/), [LEAN indicators](https://www.quantconnect.com/docs/v2/writing-algorithms/indicators/supported-indicators), [TradingView Technical Ratings](https://www.tradingview.com/support/solutions/43000614331-technical-ratings/), [TradingView chart studies](https://www.tradingview.com/charting-library-docs/latest/ui_elements/indicators/Indicators-List/)
