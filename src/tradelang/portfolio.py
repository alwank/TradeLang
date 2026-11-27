"""Compose single-market strategies on one causal clock and cash account."""

from collections import Counter
from dataclasses import dataclass
from functools import cache
from heapq import heappop, heappush
from importlib.resources import files
from json import loads
from math import isfinite
from typing import ClassVar, Literal, cast

from lark import Lark, UnexpectedInput

from .data import Dataset, PreparedWindow, instant, prepare_window
from .decision import DecisionLog
from .engine import costs, execution_steps, metrics, purchase
from .model import Problem, Span, Strategy
from .portfolio_book import PortfolioBook, PortfolioPhase, ledger_total
from .workload import MEMORY_LIMIT_BYTES, Workload, admit_workload

PORTFOLIO_VERSION: Literal[9] = 9
PORTFOLIO_SEMANTICS = "9.0.0"
MAX_ASSETS = 8
MARK_STORAGE_PER_BAR = 4096
PORTFOLIO_POLICY = {
    "clock": "observed_utc_open_close_v1",
    "intrabar": "post_at_containing_close",
    "priority": "declaration_order_after_reductions",
    "currency": "one_quote_currency",
    "short_margin": "isolated_position_reserve",
    "benchmark": "equal_capital_buy_and_hold_v1",
    "terminal": "mark_to_market",
}


@dataclass(frozen=True)
class PortfolioSpec:
    version: ClassVar[Literal[9]] = PORTFOLIO_VERSION
    source: bytes
    name: str
    assets: tuple[str, ...]
    capital: float
    currency: str
    max_positions: int

    def public(self) -> dict:
        return dict(
            schema_version=PORTFOLIO_VERSION,
            dsl_version=PORTFOLIO_VERSION,
            kind="portfolio",
            name=self.name,
            assets=list(self.assets),
            capital=self.capital,
            currency=self.currency,
            max_positions=self.max_positions,
        )


@dataclass(frozen=True)
class AssetInputs:
    strategy: Strategy
    primary: Dataset
    profile: Dataset | None = None
    feeds: dict[str, Dataset] | None = None


@dataclass(frozen=True)
class PortfolioPreparation:
    spec: PortfolioSpec
    assets: tuple[tuple[str, AssetInputs, PreparedWindow], ...]
    workload: Workload


@cache
def portfolio_parser():
    grammar = files("tradelang").joinpath("grammar-v9.lark").read_text()
    return Lark(grammar, parser="lalr", propagate_positions=True)


def compile_portfolio(source: bytes | str) -> PortfolioSpec:
    raw = source.encode() if isinstance(source, str) else source
    if len(raw) > 65_536:
        raise Problem("E207_LIMIT", "Portfolio source exceeds 65,536 bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise Problem("E101_SYNTAX", "Portfolio source must be UTF-8") from error

    def span(start, end, line, column, end_line, end_column):
        bom = 3 if raw.startswith(b"\xef\xbb\xbf") else 0
        return Span(
            start_line=line,
            start_column=column,
            start_byte=bom + len(text[:start].encode()),
            end_line=end_line,
            end_column=end_column,
            end_byte=bom + len(text[:end].encode()),
        )

    try:
        name_token, *asset_trees, terms, position_limit = (
            portfolio_parser().parse(text).children
        )
    except UnexpectedInput as error:
        offset = error.pos_in_stream
        raise Problem(
            "E101_SYNTAX",
            "Expected a version 9 portfolio, asset aliases, capital, and an open-position limit",
            span(offset, offset, error.line, error.column, error.line, error.column),
        ) from error
    try:
        name = loads(name_token)
    except ValueError as error:
        raise Problem("E101_SYNTAX", "Invalid portfolio name") from error
    if not 1 <= len(name) <= 120 or not name.isprintable():
        raise Problem("E101_SYNTAX", "Invalid portfolio name")
    aliases: list[str] = []
    for declaration in asset_trees:
        token = declaration.children[0]
        if token in aliases:
            raise Problem(
                "E305_PORTFOLIO",
                f"Duplicate asset alias {token}",
                span(
                    token.start_pos,
                    token.end_pos,
                    token.line,
                    token.column,
                    token.end_line,
                    token.end_column,
                ),
            )
        aliases.append(str(token))
    if not 2 <= len(aliases) <= MAX_ASSETS:
        raise Problem(
            "E305_PORTFOLIO", f"Supply two through {MAX_ASSETS} distinct assets"
        )
    amount, currency = terms.children
    capital = float(amount)
    limit_token = position_limit.children[0]
    limit = int(limit_token) if len(limit_token) <= 2 else MAX_ASSETS + 1
    if not isfinite(capital) or capital <= 0:
        raise Problem("E305_PORTFOLIO", "Portfolio capital must be positive and finite")
    if not 1 <= limit <= len(aliases):
        raise Problem(
            "E305_PORTFOLIO", "Position limit must be within the declared asset count"
        )
    return PortfolioSpec(raw, name, tuple(aliases), capital, str(currency), limit)


def prepare_portfolio(
    spec: PortfolioSpec, inputs: dict[str, AssetInputs]
) -> PortfolioPreparation:
    missing, extra = set(spec.assets) - inputs.keys(), inputs.keys() - set(spec.assets)
    if missing or extra:
        raise Problem(
            "E305_PORTFOLIO",
            "Bind each declared asset alias exactly once",
            details={
                "missing": ", ".join(sorted(missing)),
                "extra": ", ".join(sorted(extra)),
            },
        )
    assets = []
    markets: set[str] = set()
    for name in spec.assets:
        item = inputs[name]
        symbol = item.primary.meta.symbol
        if symbol in markets:
            raise Problem("E305_PORTFOLIO", f"{name} repeats market {symbol}")
        markets.add(symbol)
        if (
            spec.currency != item.strategy.config.currency
            or spec.currency != item.primary.meta.quote_currency
        ):
            raise Problem(
                "E305_PORTFOLIO",
                f"{name} must use the portfolio quote currency {spec.currency}",
            )
        try:
            window = prepare_window(
                item.strategy, item.primary, item.profile, feeds=item.feeds
            )
        except Problem as error:
            item_diagnostic = error.diagnostic
            raise Problem(
                item_diagnostic["code"],
                f"{name}: {item_diagnostic['message']}",
                suggestion=item_diagnostic["suggestion"],
                details={**(item_diagnostic.get("details") or {}), "asset": name},
            ) from error
        assets.append((name, item, window))
    workloads = [window.workload for _, _, window in assets]
    dominant = max(workloads, key=lambda workload: workload["minimum_resident_bytes"])
    totals: Counter[str] = Counter()
    for workload in workloads:
        totals.update(
            {
                key: value
                for key, value in workload.items()
                if isinstance(value, int)
                and key
                not in {
                    "schema_version",
                    "memory_limit_bytes",
                    "dominant_expression_series",
                }
            }
        )
    mark_bytes = totals["execution_rows"] * MARK_STORAGE_PER_BAR
    resident = totals["minimum_resident_bytes"] - totals["curve_bytes"] + mark_bytes
    aggregate = cast(
        Workload,
        {
            **dominant,
            **totals,
            "curve_bytes": mark_bytes,
            "minimum_resident_bytes": resident,
            "memory_limit_bytes": MEMORY_LIMIT_BYTES,
        },
    )
    admit_workload(aggregate)
    return PortfolioPreparation(spec, tuple(assets), aggregate)


def execute_portfolio(spec: PortfolioSpec, inputs: dict[str, AssetInputs]) -> dict:
    return execute_portfolio_prepared(prepare_portfolio(spec, inputs))


def execute_portfolio_prepared(
    prepared: PortfolioPreparation,
    *,
    progress=None,
    decisions: dict[str, DecisionLog] | None = None,
) -> dict:
    spec = prepared.spec
    total = prepared.workload["execution_rows"]
    if progress is not None:
        progress(0, total)
    book = PortfolioBook(spec.capital, spec.max_positions)
    lanes = [book.attach(name) for name, _, _ in prepared.assets]
    engines = [
        execution_steps(
            item.strategy,
            item.primary,
            window,
            lane=lane,
            decisions=decisions[lane.name] if decisions is not None else None,
        )
        for lane, (_, item, window) in zip(lanes, prepared.assets, strict=True)
    ]
    queue = [(next(engine), priority) for priority, engine in enumerate(engines)]
    queue.sort()
    results: dict[str, dict] = {}
    equity_rows: list[dict] = []
    asset_rows: list[dict] = []
    completed = 0

    first_at = previous = queue[0][0].timestamp
    peak = benchmark_peak = spec.capital
    benchmark_cash = spec.capital
    share = spec.capital / len(lanes)
    budgets = [share] * (len(lanes) - 1) + [spec.capital - share * (len(lanes) - 1)]
    benchmark_quantities = [0.0] * len(lanes)
    benchmark_costs = costs()
    benchmark_opens = [
        item.primary.times[window.first_signal + 1]
        for _, item, window in prepared.assets
    ]
    exposed_us = benchmark_exposed_us = 0

    def record_mark(when, touched, *, phase):
        nonlocal peak, benchmark_peak
        equity = book.equity
        net = ledger_total(lane.market_value for lane in lanes)
        gross = ledger_total(abs(lane.market_value) for lane in lanes)
        bench = ledger_total(
            [
                benchmark_cash,
                *(
                    qty * lane.mark_price
                    for lane, qty in zip(lanes, benchmark_quantities, strict=True)
                ),
            ]
        )
        peak, benchmark_peak = max(peak, equity), max(benchmark_peak, bench)
        cumulative = equity / spec.capital - 1
        if not isfinite(cumulative) or not isfinite(book.available_cash):
            raise Problem("E_NUMERIC_EXECUTION", "Nonfinite portfolio mark")
        equity_rows.append(
            dict(
                index=len(equity_rows),
                timestamp=instant(when),
                phase=phase,
                cash=book.cash,
                reserved_cash=book.reserved_cash,
                available_cash=book.available_cash,
                net_market_value=net,
                gross_market_value=gross,
                equity=equity,
                peak_equity=peak,
                drawdown=equity / peak - 1,
                cumulative_return=cumulative,
                open_positions=book.open_positions,
                benchmark_cash=benchmark_cash,
                benchmark_equity=bench,
                benchmark_peak_equity=benchmark_peak,
                benchmark_drawdown=bench / benchmark_peak - 1,
            )
        )
        for priority in sorted(touched):
            asset_rows.append({"timestamp": instant(when), **lanes[priority].mark()})

    record_mark(first_at, (), phase="initial")
    while queue:
        step, _ = queue[0]
        when, phase = step.timestamp, step.phase
        touched: set[int] = set()
        elapsed = when - previous
        if book.open_positions:
            exposed_us += elapsed
        if any(benchmark_quantities):
            benchmark_exposed_us += elapsed
        previous = when
        while queue and queue[0][0].timestamp == when:
            phase = queue[0][0].phase
            batch = []
            while (
                queue and queue[0][0].timestamp == when and queue[0][0].phase == phase
            ):
                batch.append(heappop(queue))
            for step, priority in batch:
                if phase != PortfolioPhase.COMMIT_AT_OPEN:
                    lanes[priority].observe(step)
                    touched.add(priority)
                if (
                    phase == PortfolioPhase.REDUCE_AT_OPEN
                    and step.timestamp == benchmark_opens[priority]
                ):
                    _, item, _ = prepared.assets[priority]
                    fee, slip = (
                        item.strategy.config.fee_rate,
                        item.strategy.config.slippage_rate,
                    )
                    qty, fill, cost = purchase(budgets[priority], step.price, fee, slip)
                    benchmark_cash -= qty * fill + cost
                    benchmark_quantities[priority] = qty
                    benchmark_costs["entry_fees"] += cost
                    benchmark_costs["total_fees"] += cost
                    slippage = qty * abs(fill - step.price)
                    benchmark_costs["entry_slippage_cost"] += slippage
                    benchmark_costs["total_slippage_cost"] += slippage
            for _, priority in batch:
                try:
                    heappush(queue, (next(engines[priority]), priority))
                except StopIteration as result:
                    results[lanes[priority].name] = result.value
                if phase == PortfolioPhase.CLOSE:
                    completed += 1
                    if progress is not None and (
                        completed == total or completed % 256 == 0
                    ):
                        progress(completed, total)
        record_mark(when, touched, phase="mark")

    portfolio_costs = {
        key: ledger_total(result["costs"][key] for result in results.values())
        for key in (*costs(), "total_borrow_cost")
    }
    last_fill = {
        row["trade_id"]: row["sequence"] for row in book.events if row["kind"] == "fill"
    }
    trades = sorted(
        (trade for row in results.values() for trade in row["trades"]),
        key=lambda trade: last_fill[trade["trade_id"]],
    )
    diagnostics = [
        {**warning, "asset": name}
        for name, result in results.items()
        for warning in result["warnings"]
    ]
    duration = (previous - first_at) / 1_000_000
    strategy_metrics = metrics(
        [point["equity"] for point in equity_rows],
        trades,
        portfolio_costs,
        0,
        1,
        duration,
        True,
        session_based=True,
        can_be_insolvent=True,
    )
    benchmark_metrics = metrics(
        [point["benchmark_equity"] for point in equity_rows],
        [],
        benchmark_costs,
        0,
        1,
        duration,
        True,
        session_based=True,
    )
    strategy_metrics["exposure_fraction"] = exposed_us / (previous - first_at)
    benchmark_metrics["exposure_fraction"] = benchmark_exposed_us / (
        previous - first_at
    )
    summary = dict(
        schema_version=1,
        kind="portfolio",
        quote_currency=spec.currency,
        starting_capital=spec.capital,
        final_cash=book.cash,
        final_equity=book.equity,
        reserved_cash=book.reserved_cash,
        available_cash=book.available_cash,
        net_market_value=equity_rows[-1]["net_market_value"],
        gross_market_value=equity_rows[-1]["gross_market_value"],
        assets=[
            {
                **lane.mark(),
                "symbol": item.primary.meta.symbol,
                "open_position": results[lane.name]["open_position"],
                "counts": results[lane.name]["counts"],
                "warning_counts": results[lane.name]["warning_counts"],
            }
            for lane, (_, item, _) in zip(lanes, prepared.assets, strict=True)
        ],
        benchmark=dict(
            name=PORTFOLIO_POLICY["benchmark"],
            final_cash=benchmark_cash,
            final_equity=equity_rows[-1]["benchmark_equity"],
            costs=benchmark_costs,
            metrics=benchmark_metrics,
        ),
        benchmark_entry_at=instant(min(benchmark_opens)),
        metrics=strategy_metrics,
        metric_unavailability={"sharpe": "independent_market_clocks"},
        costs=portfolio_costs,
        warnings=diagnostics,
        window=dict(first_open=instant(first_at), last_close_at=instant(previous)),
    )
    return dict(
        schema_version=1,
        summary=summary,
        equity=equity_rows,
        asset_marks=asset_rows,
        trades=trades,
        events=book.events,
        diagnostics=diagnostics,
    )
