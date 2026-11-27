"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, read } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import type { components } from "@/lib/schema";
import { isActive, runStatus, useRunStatus, type Run } from "@/lib/run-status";
import { integer, money, numeric, presetLabel, scalar, title } from "@/lib/format";
import { EquityCharts } from "./equity-charts";
import { BarInspector } from "./bar-inspection";
import { Exports, RunOverview } from "./run-overview";
import { Time, TimeToggle } from "./shell";
import { Details, Notice, Pending } from "./ui";

function revisionLink(run: Run) {
  return `/strategies/${run.strategy_id}/revisions/${run.strategy_revision}`;
}

function PortfolioOverview({ run, summary }: { run: Run; summary: components["schemas"]["PortfolioSummary"] }) {
  const [asset, setAsset] = useState(String(summary.assets[0]?.asset ?? ""));
  const [bar, setBar] = useState<number | null>(null);
  const [eventCursor, setEventCursor] = useState<string>();
  const [eventHistory, setEventHistory] = useState<string[]>([]);
  const [tradeCursor, setTradeCursor] = useState<string>();
  const [tradeHistory, setTradeHistory] = useState<string[]>([]);
  const curve = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/backtests/{ident}/equity", {
      params: { path: { ident: run.id }, query: { mode: "envelope", max_points: 2000 } }, signal,
    },
  )), [run.id]));
  const trades = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/backtests/{ident}/trades", {
      params: { path: { ident: run.id }, query: { cursor: tradeCursor, limit: 25 } }, signal,
    },
  )), [run.id, tradeCursor]));
  const events = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/backtests/{ident}/events", {
      params: { path: { ident: run.id }, query: { cursor: eventCursor, limit: 25 } }, signal,
    },
  )), [run.id, eventCursor]));
  const marks = curve.data?.items.filter((point): point is components["schemas"]["PortfolioEquityPoint"] => "reserved_cash" in point);
  return <div className="workspace">
    <section className="section">
      <h2>Portfolio results</h2>
      <Details rows={[
        ["Final equity", money(summary.final_equity, summary.quote_currency)],
        ["Final cash", money(summary.final_cash, summary.quote_currency)],
        ["Available cash", money(summary.available_cash, summary.quote_currency)],
        ["Reserved cash", money(summary.reserved_cash, summary.quote_currency)],
        ["Net market value", money(summary.net_market_value, summary.quote_currency)],
        ["Gross market value", money(summary.gross_market_value, summary.quote_currency)],
      ]} />
      <h3>Equity</h3>
      <Notice error={curve.error} />
      {!marks && !curve.error && <Pending>Loading equity…</Pending>}
      {marks && <EquityCharts unit={summary.quote_currency}
        series={[{ id: "strategy", label: run.strategy_name }, { id: "benchmark", label: "Equal-capital benchmark" }]}
        points={marks.map((point) => ({
          timestamp: point.timestamp, phase: point.phase,
          equity: { strategy: point.equity, benchmark: point.benchmark_equity },
          drawdown: { strategy: point.drawdown, benchmark: point.benchmark_drawdown },
        }))} />}
      <h3>Assets</h3>
      <table><thead><tr><th>Asset</th><th>Market</th><th>Quantity</th><th>Mark</th><th>Market value</th><th>Realized P&amp;L</th></tr></thead>
        <tbody>{summary.assets.map((item) => <tr key={String(item.asset)}>
          <th><button className="text-button" onClick={() => { setAsset(String(item.asset)); setBar(null); }}>{String(item.asset)}</button></th>
          <td>{String(item.symbol)}</td><td>{numeric(Number(item.quantity))}</td>
          <td>{item.mark_at ? <Time value={String(item.mark_at)} /> : "—"}</td>
          <td>{money(Number(item.market_value), summary.quote_currency)}</td>
          <td>{money(Number(item.realized_net_pnl), summary.quote_currency)}</td>
        </tr>)}</tbody></table>
      <h3>Closed trades</h3>
      <Notice error={trades.error} />
      {!trades.data && !trades.error && <Pending>Loading trades…</Pending>}
      {trades.data && (trades.data.items.length ? <div className="table-scroll">
        <table aria-label="Portfolio trades"><thead><tr><th>Asset</th><th>Trade</th><th>Direction</th><th>Exit</th><th>Quantity</th><th>Net P&amp;L</th></tr></thead>
          <tbody>{trades.data.items.map((trade) => <tr key={trade.trade_id}>
            <td>{trade.asset}</td><th><button className="text-button" onClick={() => {
              if (trade.asset) setAsset(trade.asset);
              setBar(trade.entry_bar);
            }}>{trade.trade_id}</button></th>
            <td>{title(trade.direction)}</td><td><Time value={trade.exit_at} /> · {title(trade.exit_reason)}</td>
            <td>{numeric(trade.quantity)}</td><td>{money(trade.net_pnl, summary.quote_currency)}</td>
          </tr>)}</tbody></table>
      </div> : <p>No closed trades.</p>)}
      {trades.data && Boolean(tradeHistory.length || trades.data.next_cursor) && <div className="actions">
        <button className="button compact" disabled={!tradeHistory.length} onClick={() => {
          setTradeCursor(tradeHistory.at(-1) || undefined); setTradeHistory(tradeHistory.slice(0, -1));
        }}>Previous trades</button>
        <button className="button compact" disabled={!trades.data.next_cursor} onClick={() => {
          setTradeHistory([...tradeHistory, tradeCursor ?? ""]); setTradeCursor(trades.data?.next_cursor ?? undefined);
        }}>Next trades</button>
      </div>}
      <h3>Events</h3>
      <Notice error={events.error} />
      {!events.data && !events.error && <Pending>Loading events…</Pending>}
      {events.data && <div className="table-scroll"><table aria-label="Portfolio events">
        <thead><tr><th>Time</th><th>Asset</th><th>Event</th><th>Cash after</th><th>Quantity after</th></tr></thead>
        <tbody>{events.data.items.map((event) => <tr key={event.event_id}>
          <td><Time value={event.observed_at} /></td><td>{scalar(event.data.asset)}</td>
          <td>{title(event.kind)} · {title(event.reason)}</td>
          <td>{money(Number(event.data.cash_after), summary.quote_currency)}</td>
          <td>{numeric(Number(event.data.quantity_after))}</td>
        </tr>)}</tbody>
      </table></div>}
      {events.data && Boolean(eventHistory.length || events.data.next_cursor) && <div className="actions">
        <button className="button compact" disabled={!eventHistory.length} onClick={() => {
          setEventCursor(eventHistory.at(-1) || undefined); setEventHistory(eventHistory.slice(0, -1));
        }}>Previous events</button>
        <button className="button compact" disabled={!events.data.next_cursor} onClick={() => {
          setEventHistory([...eventHistory, eventCursor ?? ""]); setEventCursor(events.data?.next_cursor ?? undefined);
        }}>Next events</button>
      </div>}
    </section>
    <aside className="inspector">
      <label className="inline-field">Inspect asset
        <select value={asset} onChange={(event) => { setAsset(event.currentTarget.value); setBar(null); }}>
          {summary.assets.map((item) => <option key={String(item.asset)} value={String(item.asset)}>{String(item.asset)} · {String(item.symbol)}</option>)}
        </select>
      </label>
      {asset && <BarInspector key={asset + bar} runId={run.id} index={bar} asset={asset}
        currency={summary.quote_currency} inspect={setBar} />}
    </aside>
  </div>;
}

export function RunDetail({ id, strategyId, active = true, sourceUrl }: {
  id: string; strategyId?: string; active?: boolean; sourceUrl?: string;
}) {
  const { run, error, cancelling, retry, cancel } = useRunStatus(id);
  const heading = useRef<HTMLHeadingElement>(null);
  const resolved = Boolean(run || error);
  useEffect(() => {
    if (strategyId && active && resolved) heading.current?.focus();
  }, [strategyId, id, active, resolved]);

  const returnLink = <Link href={sourceUrl ?? "/runs"}>{sourceUrl ? "Return to source" : "Open run history"}</Link>;
  if (!run) return error ? <>
    <h1 ref={heading} tabIndex={-1}>Run unavailable</h1><Notice error={error} />
    <div className="actions"><button className="button" onClick={retry}>Retry</button>{returnLink}</div>
  </> : <Pending>Loading backtest…</Pending>;
  if (strategyId && strategyId !== run.strategy_id) return <div className="route-fallback">
    <h1 ref={heading} tabIndex={-1}>This run belongs to another strategy</h1>
    <div className="actions"><Link href={`/runs/${run.id}`}>Open standalone run</Link>{returnLink}</div>
  </div>;
  const live = isActive(run);
  const config = run.configuration;
  const workspacePath = `/strategies/${run.strategy_id}`;
  const workspaceQuery = new URLSearchParams();
  if (run.dataset_id) workspaceQuery.set("dataset", run.dataset_id);
  const newRunUrl = workspaceQuery.size ? `${workspacePath}?${workspaceQuery}` : workspacePath;
  workspaceQuery.set("run", run.id);

  return <>
    <div className="page-heading bar run-heading">
      <div className="heading-copy">
        <h1 ref={heading} tabIndex={-1}>{run.strategy_name}</h1>
        <p className="muted">{scalar(config.market)} · {run.dataset_name} · Revision {run.strategy_revision} ·{" "}
          <Link href={revisionLink(run)}>View strategy</Link>
        </p>
      </div>
      <div className="actions">
        <TimeToggle />
        {sourceUrl ? <Link href={`/runs/${run.id}`}>Open standalone run</Link> :
          <Link href={`${workspacePath}?${workspaceQuery}`}>Open strategy workspace</Link>}
        {run.status === "succeeded" && <Exports id={run.id} configured={Boolean(
          config.effective || config.feeds || config.session_calendar || config.short_margin || config.portfolio_assets
        )} portfolio={Boolean(config.portfolio_assets)} />}
      </div>
    </div>
    <Notice error={error} />
    {Boolean(error) && <div className="actions"><span>Showing the last known run status.</span><button className="button compact" onClick={retry}>Retry status</button></div>}
    {run.status === "succeeded" && run.summary ? "kind" in run.summary ?
      <PortfolioOverview key={id} run={run} summary={run.summary} /> :
      <RunOverview key={id} run={run} summary={run.summary} active={active} /> :
      <div className="workspace">
        <section className="section">
          {live ? <>
            <h2 className="run-state" role="status">{cancelling ? "Requesting cancellation…" : runStatus(run)}</h2>
            <p className="muted">Submitted <Time value={run.created_at} /></p>
            {run.status === "running" && run.progress.total_bars > 0 && <div className="progress">
              <label htmlFor="backtest-progress">
                {integer.format(run.progress.completed_bars)} of {integer.format(run.progress.total_bars)} candles processed
              </label>
              <progress id="backtest-progress" value={run.progress.completed_bars} max={run.progress.total_bars} />
              <p className="muted">Time limit · {run.time_limit} s</p>
            </div>}
            <button className="button" disabled={cancelling || run.cancel_requested} onClick={cancel}>
              {run.cancel_requested ? "Cancellation requested" : "Cancel run"}
            </button>
          </> : <>
            <h2>{runStatus(run)}</h2>
            <p>{run.error?.message ?? (run.status === "cancelled" ? "The backtest was cancelled." : "The backtest ended before publishing a result.")}</p>
            {run.error?.diagnostics.length ? <ul>{run.error.diagnostics.map((item, index) =>
              <li key={index}>{item.message}{item.suggestion ? ` ${item.suggestion}` : ""}</li>)}</ul> : null}
            <div className="actions section-heading">
              <Link className="button" href={revisionLink(run)}>View strategy</Link>
              <Link className="button primary" href={newRunUrl}>New run</Link>
            </div>
          </>}
        </section>
        <aside className="inspector">
          <h2>Run assumptions</h2>
          <Details rows={[
            ["Dataset fingerprint", <code key="hash">{run.dataset_hash}</code>],
            ["Run preset", presetLabel(config.preset)],
            ["Starting capital", `${scalar(config.capital)} ${scalar(config.currency)}`],
            ["Fee per side", `${numeric(Number(config.fee_rate) * 10000)} bps`],
            ["Slippage per side", `${numeric(Number(config.slippage_rate) * 10000)} bps`],
            ["First executable open", <Time key="execute" value={run.resolved_window.first_execution_at} />],
            ["Final holdings", "Marked at final close"],
          ]} />
        </aside>
      </div>}
  </>;
}
