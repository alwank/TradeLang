# Backtesting basics

A backtest applies a strategy to past prices and simulates what would have happened under stated rules. TradeLang runs one long spot position at a time on a 24/7 UTC calendar. A long spot position buys an asset with cash and later sells it.

## Read a candle

A candle summarizes trading during a fixed interval, such as one hour or one day. Its **OHLCV** fields are the opening price, highest price, lowest price, closing price, and quantity traded. TradeLang timestamps a candle at the start of its interval in UTC. For example, the daily candle labeled January 1 opens at midnight on January 1 and completes at midnight on January 2.

The [quickstart candles](fixtures/core.csv) are synthetic and use the example market `TESTUSDT`, quoted in USDT.

| Candle (UTC) | Open | High | Low | Close | Volume |
| --- | ---: | ---: | ---: | ---: | ---: |
| Jan 1 | 100 | 102 | 98 | 100 | 10 |
| Jan 2 | 110 | 115 | 108 | 112 | 20 |
| Jan 3 | 120 | 125 | 115 | 120 | 30 |

## Follow a signal to a fill

A **signal** is a decision from the strategy’s rules. A **fill** is the simulated execution of an order at a price and quantity. TradeLang evaluates ordinary entry and exit rules when a candle completes. The resulting order can fill at the next observed candle’s open.

1. The example allows a buy whenever it is flat and the exit rule is false. On the January 1 close of 100 USDT, it queues a buy. The January 2 open fills it at 110 USDT.
2. The exit rule triggers when the close reaches at least 112 USDT. The January 2 close meets that rule and queues a sell. The January 3 open fills it at 120 USDT.

The January 2 close and January 3 open share a UTC timestamp. The event sequence records the close decision before the opening fill. See the [quickstart trade trace](results.md#trace-the-quickstart-trade).

## Account for size and costs

**Position size** is how much of your cash or equity you commit to a trade. With 1,000 USDT and zero fees, the example buys `1000 / 110` units. Selling those units at 120 USDT leaves about **1,090.91 USDT**. Committing 25% buys one quarter as many units and leaves the rest in cash.

The strategy can specify **fees** and **slippage** per side, so they apply at entry and exit. Fees are charged on traded value and the entry fee comes from the buy budget. Slippage models a worse execution price by increasing buy prices and decreasing sell prices. Both are configured in basis points, where 10 basis points is 0.10%. The tutorial uses zero for both so the result can be checked by hand. See [execution semantics](execution-semantics.md).

## Interpret the result

**Equity** is cash plus the current value of any open position. The backtest records equity over time, completed trades, and the events behind each decision. These help you check whether the rules behaved as intended on the supplied candles. Results depend on the date range, data, and execution assumptions. The synthetic examples demonstrate the workflow and carry no evidence about future performance.

Next, [run your first backtest](quickstart.md) and find the signals and fills in the output files.
