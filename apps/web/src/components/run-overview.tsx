"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { api, read } from "@/lib/api";
import { feedLabels, integer, memory, money, numeric, presetLabel, ratio, scalar, title } from "@/lib/format";
import type { components } from "@/lib/schema";
import { useResource } from "@/lib/use-resource";
import { BarInspector } from "./bar-inspection";
import { EquityCharts } from "./equity-charts";
import type { Run } from "@/lib/run-status";
import { Time, usePane } from "./shell";
import { Details, Notice, Pending } from "./ui";

type Summary = components["schemas"]["ResultSummary"];
type Trade = components["schemas"]["Trade"];
type Equity = components["schemas"]["EquityPoint"];
type Range = { from_index: number; to_index: number };
const series = [{ id: "strategy", label: "Strategy" }, { id: "benchmark", label: "Buy-and-hold, warmup aligned" }];
const exports = [
  ["Summary", "summary.json"], ["Trades", "trades.csv"], ["Full equity CSV", "equity.csv"],
  ["Full equity Parquet", "equity.parquet"], ["Events", "events.jsonl"],
  ["Manifest", "manifest.json"], ["Strategy source", "source.trade"],
];
const reasons = ["signal_exit", "stop_gap", "target_gap", "stop_entry_open", "stop_touch", "target_touch", "stop_dual_touch"];
const liquidationReasons = ["liquidation_gap", "liquidation_entry_open", "liquidation_touch", "liquidation_close"];

export function Exports({ id, configured, portfolio = false }: { id: string; configured: boolean; portfolio?: boolean }) {
  const files = [
    ...exports,
    ...(configured ? [["Replay configuration", "run-config.json"]] : []),
    ...(portfolio ? [["Asset marks CSV", "asset-marks.csv"], ["Asset marks Parquet", "asset-marks.parquet"]] : []),
  ];
  return <details className="disclosure"><summary>Download exports</summary>
    <ul>{files.map(([label, name]) => <li key={name}>
      <a href={`/api/v1/backtests/${id}/artifacts/${name}`} download>{label}</a>
    </li>)}</ul>
  </details>;
}

export function RunOverview({ run, summary, active }: { run: Run; summary: Summary; active: boolean }) {
  const id = run.id;
  const metrics = summary.metrics;
  const currency = summary.quote_currency;
  const short = summary.short_accounting;
  const [unit, setUnit] = useState<"money" | "index">("money");
  const [range, setRange] = useState<Range>();
  const [reason, setReason] = useState("");
  const [barIndex, setBarIndex] = useState<number>();
  const candleDecision = useRef<HTMLDivElement>(null);
  const [cursor, setCursor] = useState<string>();
  const [prior, setPrior] = useState<string[]>([]);
  const [selected, setSelected] = useState<Trade>();
  const [holding, setHolding] = useState(false);
  const [inspectorOpen, setInspectorOpen] = usePane("tradeInspector");
  const [selectionCleared, setSelectionCleared] = useState(false);
  const opener = useRef<HTMLElement>(null);
  const inspector = useRef<HTMLElement>(null);
  const reveal = useRef(false);

  useEffect(() => {
    if (active && inspectorOpen && reveal.current) {
      reveal.current = false;
      inspector.current?.querySelector<HTMLHeadingElement>("h2")?.focus();
    }
  }, [active, inspectorOpen, selected, holding]);

  function revealInspector(element: HTMLElement, next?: Trade) {
    opener.current = element;
    if (!inspectorOpen || window.matchMedia("(max-width: 959px)").matches) {
      reveal.current = true;
      setInspectorOpen(true);
      if (next?.trade_id === selected?.trade_id && (next || holding) && inspectorOpen) {
        reveal.current = false;
        inspector.current?.querySelector<HTMLHeadingElement>("h2")?.focus();
      }
    }
    setSelectionCleared(false);
    setSelected(next);
    setHolding(!next);
  }

  function closeDetails() {
    setSelected(undefined);
    setHolding(false);
    opener.current?.focus();
  }
  const curve = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/backtests/{ident}/equity", {
      params: { path: { ident: id }, query: { mode: "envelope", max_points: 2000, ...range } }, signal,
    },
  )), [id, range]));
  const trades = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/backtests/{ident}/trades", {
      params: { path: { ident: id }, query: { reason: reason || undefined, cursor, limit: 25 } }, signal,
    },
  )), [id, reason, cursor]));
  const chart = curve.data?.items.filter((point): point is Equity => "bar_index" in point);
  const firstBar = chart?.find((point) => point.bar_index !== null)?.bar_index;
  function inspectBar(index: number) {
    setBarIndex(index);
    requestAnimationFrame(() => {
      const panel = candleDecision.current;
      panel?.scrollIntoView({ block: "nearest" });
      panel?.querySelector("input")?.focus({ preventScroll: true });
    });
  }
  const scale = unit === "index" ? 100 / summary.starting_capital : 1;
  const visibleWarnings = summary.warnings.filter((warning) => warning.severity !== "info");

  const metric = (key: string, rendered: string) => {
    const reason = summary.warnings.find((item) => item.details?.account === "strategy" && item.details?.metric === key);
    return reason ? <>{rendered} <small className="muted">({String(reason.details?.reason).replaceAll("_", " ")})</small></> : rendered;
  };
  return <div className="run-overview">
    <div className="bar run-notes">
      <div className="actions">
        {visibleWarnings.length > 0 && <span className="warning-text">
          {visibleWarnings.some((warning) => warning.code === "W_WARMUP_DELAY")
            ? "Warmup delayed first execution" : visibleWarnings[0].message}
          {visibleWarnings.length > 1 && ` · ${visibleWarnings.length} warnings in Run details`}
        </span>}
        {summary.open_position && <button className="text-button"
          onClick={(event) => revealInspector(event.currentTarget)}>View open position</button>}
      </div>
      <div className="actions">
      <p className="muted"><Time value={run.resolved_window.first_open} /> – <Time value={run.resolved_window.last_close_at} /></p>
      <details className="disclosure"><summary>Run details</summary>
      <Details rows={[
        ["Dataset fingerprint", <code key="hash">{run.dataset_hash}</code>],
        ...(feedLabels(run.configuration.feeds).length ? [
          ["Higher-timeframe feeds", feedLabels(run.configuration.feeds).join(", ")] as [string, string],
        ] : []),
        ["Engine", scalar(run.configuration.engine_version)], ["Semantics", scalar(run.configuration.semantics_version)],
        ["Run preset", presetLabel(run.configuration.preset)],
        ["Starting capital", money(Number(run.configuration.capital), currency)],
        ["Fee per side", `${numeric(Number(run.configuration.fee_rate) * 10000)} bps`],
        ["Slippage per side", `${numeric(Number(run.configuration.slippage_rate) * 10000)} bps`],
        ...Object.entries(run.configuration.parameters ?? {}).map(
          ([name, value]): [string, string] => [`Parameter ${name}`, String(value)],
        ),
        ["Final cash", money(summary.final_cash, currency)], ["CAGR", metric("cagr", ratio(metrics.cagr))],
        ["Sharpe", metric("sharpe", numeric(metrics.sharpe))], ["Win rate", metric("win_rate", ratio(metrics.win_rate))],
        ["Profit factor", metric("profit_factor", numeric(metrics.profit_factor))],
        ["Fees debited", money(metrics.total_fees, currency)], ["Slippage in fill prices", money(metrics.total_slippage_cost, currency)],
        ...(short ? [
          ["Borrow costs", money(summary.costs.total_borrow_cost, currency)],
          ["Liquidations", integer.format(short.liquidations)],
          ["Reserved cash", money(short.reserved_cash, currency)],
          ["Available cash", money(short.available_cash, currency)],
          ["Account status", short.insolvent ? "Insolvent" : "Solvent"],
        ] as [string, string][] : []),
        ...(summary.position_accounting ? [
          ["Realized net P&L", money(summary.position_accounting.realized_net_pnl, currency)],
          ["Position fills", integer.format(summary.position_accounting.fill_count)],
        ] as [string, string][] : []),
        ["Benchmark entry", <Time key="bench" value={summary.benchmark_entry_at} />],
        ["Benchmark entry fee", money(Number(summary.benchmark.entry_fee), currency)],
        ["Benchmark final position", "Marked at final close"],
        ...(run.workload ? [
          ["Minimum resident storage", memory(run.workload.minimum_resident_bytes)],
          ["Worker memory budget", memory(run.workload.memory_limit_bytes)],
        ] as [string, string][] : []),
      ]} />
        {summary.warnings.length > 0 && <ul>{summary.warnings.map((warning, index) =>
          <li key={index}>{warning.message}</li>)}</ul>}
      </details>
        <button className="text-button" aria-expanded={inspectorOpen} aria-controls="trade-inspector"
          onClick={(event) => {
            if (!inspectorOpen) {
              opener.current = event.currentTarget;
              reveal.current = true;
            }
            setInspectorOpen(!inspectorOpen);
          }}>{inspectorOpen ? "Hide trade inspector" : "Show trade inspector"}</button>
      </div>
    </div>
    <dl className="metrics">
      {[["Total return", ratio(metrics.total_return)], ["Final equity", money(summary.final_equity, currency)],
        ["Max drawdown", ratio(metrics.max_drawdown)], ["Closed trades", integer.format(metrics.closed_trades)]].map(([label, value]) =>
        <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
    </dl>
    <div className={inspectorOpen ? "workspace result-workspace" : "workspace result-workspace inspector-hidden"}>
      <section aria-label="Backtest results">
        <section className="section chart-section">
          <div className="bar section-heading">
            <p className="muted">
              {curve.data && !curve.data.full_resolution ? `Sampled view · ${curve.data.returned_points} of ${curve.data.total_points} marks`
                : <>Benchmark entry · <Time value={summary.benchmark_entry_at} /></>}
            </p>
            <div className="actions"><label className="inline-field">Equity display
              <select value={unit} onChange={(event) => setUnit(event.target.value as typeof unit)}>
                <option value="money">{currency}</option><option value="index">Index 100</option>
              </select>
            </label>
            <button className="text-button" disabled={!range} onClick={() => setRange(undefined)}>Reset zoom</button></div>
          </div>
          <div className="actions">
            <button className="text-button" disabled={firstBar == null}
              onClick={() => firstBar != null && inspectBar(firstBar)}>Inspect a candle</button>
          </div>
          <Notice error={curve.error} />
          {curve.error ? <button className="button" onClick={curve.reload}>Retry chart</button> :
            !chart ? <Pending>Loading equity…</Pending> : active && <>
              <EquityCharts series={[{ ...series[0], label: run.strategy_name }, series[1]]} unit={unit === "money" ? currency : "Index 100"}
                points={chart.map((point) => ({
                  timestamp: point.timestamp, phase: point.phase,
                  equity: { strategy: point.equity * scale, benchmark: point.benchmark_equity * scale },
                  drawdown: { strategy: point.drawdown, benchmark: point.benchmark_drawdown },
                }))}
                controls={<ZoomControls key={chart[0]?.index + ":" + chart.at(-1)?.index}
                  points={chart} onZoom={setRange} reset={() => setRange(undefined)} />} />
            </>}
        </section>
        {barIndex !== undefined && <div ref={candleDecision}>
          <BarInspector key={barIndex} runId={id} index={barIndex} currency={currency}
            totalBars={run.progress.total_bars} inspect={inspectBar} />
        </div>}
        <section className="section trade-section">
          <div className="bar section-heading">
            <h2>Closed trades</h2>
            <label className="inline-field">Exit reason
              <select value={reason} onChange={(event) => {
                const filter = event.target.value;
                const removed = Boolean(selected && filter && selected.exit_reason !== filter);
                setSelectionCleared(removed);
                if (removed) setSelected(undefined);
                setReason(filter);
                setCursor(undefined);
                setPrior([]);
              }}>
                <option value="">All</option>
                {[...reasons, ...(short ? liquidationReasons : [])].map((value) =>
                  <option key={value} value={value}>{title(value)}</option>)}
              </select>
            </label>
          </div>
          <Notice error={trades.error} />
          {trades.error ? <button className="button" onClick={trades.reload}>Retry trades</button> :
            !trades.data ? <Pending>Loading trades…</Pending> : trades.data.items.length ? <div className="table-wrap trade-table" tabIndex={0} role="region" aria-label="Closed trades ledger">
              <table><thead><tr><th>Trade</th><th>Entry</th><th>Exit</th><th>Reason</th><th className="number">Net P&L</th></tr></thead>
                <tbody>{trades.data.items.map((trade) => <tr key={trade.trade_id} className={selected?.trade_id === trade.trade_id ? "selected" : ""}>
                  <td><button className="text-button numeric" aria-pressed={selected?.trade_id === trade.trade_id}
                    onClick={(event) => revealInspector(event.currentTarget, trade)}>{trade.trade_id}</button></td>
                  <td><Time value={trade.entry_at} /></td>
                  <td>{trade.exit_time_precision !== "open" && <span className="subline">
                    {trade.exit_time_precision === "bar" ? "Within candle" : "At close"}
                  </span>}<Time value={trade.exit_at} /></td>
                  <td>{title(trade.exit_reason)}</td>
                  <td className="number numeric">{money(trade.net_pnl, currency)}</td>
                </tr>)}</tbody></table>
              {Boolean(prior.length || trades.data.next_cursor) && <div className="actions table-actions">
                <button className="button compact" disabled={prior.length === 0} onClick={() => {
                  setCursor(prior.at(-1) || undefined);
                  setPrior(prior.slice(0, -1));
                }}>Previous page</button>
                <button className="button compact" disabled={!trades.data.next_cursor} onClick={() => {
                  setPrior([...prior, cursor ?? ""]);
                  setCursor(trades.data?.next_cursor ?? undefined);
                }}>Next page</button>
              </div>}
            </div> : <div className="empty">
              <p>{reason ? "No trades match this exit reason." : "No closed trades."}</p>
              {summary.open_position && <p>This run ended with an open position.</p>}
            </div>}
          {selectionCleared && <p role="status" className="muted">Selection cleared after changing the exit filter.</p>}
        </section>
      </section>
      <aside className="inspector trade-inspector" id="trade-inspector" ref={inspector}
        hidden={!inspectorOpen} aria-label={holding ? "Open position" : "Trade details"}>
        {holding && summary.open_position ? <>
          <div className="bar"><h2 tabIndex={-1}>Open position</h2><button className="text-button" onClick={closeDetails}>Close details</button></div>
          <Details rows={[
            ["Trade", scalar(summary.open_position.trade_id)],
            ["Quantity", scalar(summary.open_position.quantity)],
            ...(short ? [
              ["Direction", "Short"],
              ["Remaining borrow cost", money(Number(summary.open_position.remaining_borrow_cost), currency)],
              ["Reserved cash", money(short.reserved_cash, currency)],
            ] as [string, string][] : []),
            ...(summary.position_accounting ? [
              ["Remaining gross basis", money(Number(summary.open_position.remaining_gross_basis), currency)],
              ["Remaining entry fees", money(Number(summary.open_position.remaining_entry_fees), currency)],
              ["Realized net P&L", money(Number(summary.open_position.realized_net_pnl), currency)],
              ["Unrealized net P&L", money(Number(summary.open_position.unrealized_net), currency)],
            ] as [string, string][] : [
              ["Entry fee", money(Number(summary.open_position.entry_fee), currency)],
              ["Marked P&L", money(Number(summary.open_position.unrealized_gross), currency)],
            ] as [string, string][]),
          ]} />
          {summary.position_accounting && <PositionFills runId={id}
            tradeId={String(summary.open_position.trade_id)} currency={currency} short={Boolean(short)} />}
        </> : selected ? <TradeDetails key={selected.trade_id} runId={id} trade={selected}
          currency={currency} close={closeDetails} inspect={inspectBar} showLedger={Boolean(summary.position_accounting)} /> :
          <><h2 tabIndex={-1}>Trade details</h2><p className="muted">Select a closed trade to inspect its fills.</p></>}
      </aside>
    </div>
  </div>;
}

function ZoomControls({ points, onZoom, reset }: {
  points: Equity[]; onZoom: (range: Range) => void; reset: () => void;
}) {
  const first = points[0];
  const last = points.at(-1);
  const [message, setMessage] = useState("");
  if (!first || !last || points.length < 2) return null;
  function zoom(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const start = Date.parse(`${values.get("from")}Z`);
    const end = Date.parse(`${values.get("to")}Z`);
    const from = points.findLast((point) => Date.parse(point.timestamp) <= start) ?? first;
    const to = points.find((point) => Date.parse(point.timestamp) >= end) ?? last;
    if (!from || !to || !Number.isFinite(start) || !Number.isFinite(end) || start >= end || from.index >= to.index) {
      setMessage("Choose an ending time after the start.");
      return;
    }
    setMessage("");
    onZoom({ from_index: from.index, to_index: to.index });
  }
  return <details className="disclosure">
    <summary>Chart range (UTC)</summary>
    <form className="actions" onSubmit={zoom}>
      <label className="stack-field">From<input name="from" type="datetime-local" required defaultValue={first.timestamp.slice(0, 16)} /></label>
      <label className="stack-field">To<input name="to" type="datetime-local" required defaultValue={last.timestamp.slice(0, 16)} /></label>
      <button className="button compact">Zoom</button>
      <button className="button compact" type="button" onClick={reset}>Reset zoom</button>
    </form>
    {message && <p role="alert">{message}</p>}
  </details>;
}

function PositionFills({ runId, tradeId, currency, short }: {
  runId: string; tradeId: string; currency: string; short: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [cursor, setCursor] = useState<string>();
  const [previous, setPrevious] = useState<string[]>([]);
  const fills = useResource(useCallback(async (signal) => open ? read(await api.GET(
    "/api/v1/backtests/{ident}/events", {
      params: { path: { ident: runId }, query: { kind: "fill", trade_id: tradeId, cursor, limit: 25 } }, signal,
    },
  )) : undefined, [open, runId, tradeId, cursor]));
  return <details className="disclosure" onToggle={(event) => setOpen(event.currentTarget.open)}>
    <summary>Position fill ledger</summary>
    <Notice error={fills.error} />
    {open && !fills.data && !fills.error && <Pending>Loading fills…</Pending>}
    {Boolean(fills.error) && <button className="button compact" onClick={fills.reload}>Retry fills</button>}
    {fills.data && <div className="table-scroll">
      <table aria-label="Position fills">
        <thead><tr><th>Fill</th><th>Quantity</th><th>Fee</th><th>Cash after fill</th><th>Realized net P&amp;L</th>
          <th>Remaining quantity</th><th>Remaining gross basis</th><th>Remaining entry fees</th>
          {short && <th>Allocated borrow cost</th>}</tr></thead>
        <tbody>{fills.data.items.map((event) => event.ledger && <tr key={event.event_id}>
          <th scope="row">{event.ledger.leg} · {title(event.reason)}<small className="subline">
            {event.fill_id} · <Time value={event.observed_at} /></small></th>
          <td>{scalar(event.data.quantity)}</td><td>{money(Number(event.data.fee), currency)}</td>
          <td>{money(Number(event.data.cash_after), currency)}</td>
          <td>{["sell", "cover"].includes(String(event.data.side)) ? money(event.ledger.realized_net_pnl, currency) : "—"}</td>
          <td>{numeric(event.ledger.quantity_after)}</td>
          <td>{money(event.ledger.remaining_gross_basis, currency)}</td>
          <td>{money(event.ledger.remaining_entry_fees, currency)}</td>
          {short && <td>{money(event.ledger.borrow_cost_released, currency)}</td>}
        </tr>)}</tbody>
      </table>
      {Boolean(previous.length || fills.data.next_cursor) && <div className="actions table-actions">
        <button className="button compact" disabled={!previous.length} onClick={() => {
          setCursor(previous.at(-1) || undefined);
          setPrevious(previous.slice(0, -1));
        }}>Previous fills</button>
        <button className="button compact" disabled={!fills.data.next_cursor} onClick={() => {
          setPrevious([...previous, cursor ?? ""]);
          setCursor(fills.data?.next_cursor ?? undefined);
        }}>Next fills</button>
      </div>}
    </div>}
  </details>;
}

function TradeDetails({ runId, trade, currency, close, inspect, showLedger }: {
  runId: string; trade: Trade; currency: string; close: () => void; inspect: (index: number) => void; showLedger: boolean;
}) {
  const [events, setEvents] = useState(false);
  const [cursor, setCursor] = useState<string>();
  const audit = useResource(useCallback(async (signal) => events ? read(await api.GET(
    "/api/v1/backtests/{ident}/events", {
      params: { path: { ident: runId }, query: { trade_id: trade.trade_id, cursor, limit: 20 } }, signal,
    },
  )) : undefined, [runId, trade.trade_id, events, cursor]));
  const exitRule = trade.exit_rationale?.exit_rule;
  const exitRuleName = exitRule && typeof exitRule === "object" && "name" in exitRule &&
    typeof exitRule.name === "string" ? exitRule.name : null;
  return <>
    <div className="bar"><h2 tabIndex={-1}>Trade details</h2><button className="text-button" onClick={close}>Close details</button></div>
    <h3 className="trade-id numeric">{trade.trade_id}</h3>
    <p><strong className="signal-exit">{title(trade.exit_reason)}</strong><br /><Time value={trade.exit_at} /></p>
    {exitRuleName && <p>Exit rule <code>{exitRuleName}</code></p>}
    <Details rows={[
      ["Execution", { bar: "Within candle", close: "At candle close", open: "Next bar open" }[trade.exit_time_precision]],
      ["Fill price", money(trade.exit_price, currency)],
      ["Net P&L", money(trade.net_pnl, currency)],
    ]} />
    <div className="actions">
      <button className="text-button" onClick={() => inspect(trade.entry_signal_bar)}>Inspect entry candle</button>
      <button className="text-button" onClick={() => inspect(trade.entry_bar)}>Inspect fill candle</button>
    </div>
    <details className="disclosure">
      <summary>Prices, quantity, and costs</summary>
      <Details rows={[
      ["Direction", trade.direction], ["Quantity", numeric(trade.quantity)], ["Entry", <Time key="entry" value={trade.entry_at} />],
      ["Entry reference", money(trade.entry_reference, currency)], ["Entry fill", money(trade.entry_price, currency)],
      ["Exit reference", money(trade.exit_reference, currency)], ["Exit fill", money(trade.exit_price, currency)],
      ["Entry fee", money(trade.entry_fee, currency)], ["Exit fee", money(trade.exit_fee, currency)],
      ...(trade.direction === "short" ? [
        ["Initial margin", money(trade.initial_collateral, currency)],
        ["Borrow cost", money(trade.borrow_cost, currency)],
      ] as [string, string][] : []),
      ["Entry slippage", money(trade.entry_slippage_cost, currency)], ["Exit slippage", money(trade.exit_slippage_cost, currency)],
      ["Gross P&L", money(trade.gross_pnl, currency)], ["Net return", ratio(trade.return_fraction)],
      ]} />
    </details>
    {([["Entry signal", trade.entry_rationale], ["Exit signal", trade.exit_rationale], ["Protection at exit", trade.protection]] as const)
      .map(([name, data]) => data && <details className="disclosure" key={name}>
        <summary>{name}</summary><pre className="audit-values">{JSON.stringify(data, null, 2)}</pre>
      </details>)}
    {showLedger && <PositionFills runId={runId} tradeId={trade.trade_id} currency={currency} short={trade.direction === "short"} />}
    <button className="text-button" aria-expanded={events} onClick={() => { setEvents(!events); setCursor(undefined); }}>
      {events ? "Hide linked events" : "View linked events"}
    </button>
    {events && <>
      <Notice error={audit.error} />
      {!audit.data && !audit.error && <Pending />}
      <ul className="diagnostics">{audit.data?.items.map((item) => <li key={item.event_id}>
        <strong>{title(item.kind)} · {title(item.reason)}</strong>
        <small><Time value={item.bar_open_at} /> · {item.time_precision === "bar" ? "Within candle" : item.time_precision}</small>
      </li>)}</ul>
      {audit.data?.next_cursor && <button className="button compact" onClick={() => setCursor(audit.data?.next_cursor ?? undefined)}>Next events</button>}
    </>}
  </>;
}
