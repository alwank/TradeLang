"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";
import { api, read } from "@/lib/api";
import { metricDelta, metricValue, pairDifference, type Comparison, type Metric } from "@/lib/comparison-deltas";
import { feedLabels, integer, money, numeric, ratio, scalar, title } from "@/lib/format";
import { useResource } from "@/lib/use-resource";
import { EquityCharts, type PlotPoint } from "./equity-charts";
import { Time, TimeToggle } from "./shell";
import { Notice, Pending } from "./ui";

const labels: Record<string, string> = {
  currency: "Quote currency", timeframe_seconds: "Timeframe (seconds)",
  first_open: "First open", last_close_at: "Last close", capital: "Starting capital",
  fee_rate: "Fee per side", slippage_rate: "Slippage per side",
  engine_version: "Engine version", semantics_version: "Semantics version",
  benchmark_entry_at: "Benchmark entry", dataset_hash: "Dataset fingerprint",
  profile_dataset_hash: "Volume Profile fingerprint", gap_policy: "Gap policy",
};
const headline: [string, Metric][] = [
  ["Total return", "total_return"], ["Final equity", "final_equity"],
  ["Max drawdown", "max_drawdown"], ["Closed trades", "closed_trades"],
];
const expanded: [string, Metric][] = [
  ["CAGR", "cagr"], ["Sharpe", "sharpe"], ["Win rate", "win_rate"], ["Profit factor", "profit_factor"],
];

const runName = (run: Comparison["runs"][number]) => `${run.strategy_name} · rev ${run.strategy_revision}`;
const benchmarkReasons = {
  market_or_semantics_mismatch: "Market, candle interval, calendar, currency, or execution semantics differ.",
  primary_data_mismatch: "Primary candle data or gap policy differs.",
  cost_mismatch: "Fee or slippage rates differ.",
  no_overlap: "The executable windows have no shared candles.",
  numeric_range: "The reference exceeds the supported numeric range.",
  recorded_input_unavailable: "The recorded candles or equity could not be read.",
  portfolio_reference_unavailable: "The common-start reference is unavailable for portfolio runs.",
};
const benchmarkId = "common_hold";

export function CompareRuns({ ids }: { ids: string }) {
  const params = useSearchParams();
  const pin = params.getAll("baseline").length === 1 ? params.get("baseline")?.toLowerCase() : undefined;
  const selection = useResource(useCallback(async (signal) => ids ? read(await api.GET(
    "/api/v1/backtests/compare", { params: { query: { ids } }, signal },
  )) : undefined, [ids]));
  const comparison = selection.data;
  const resolvedPin = comparison?.runs.find((run) => run.run_id === pin)?.run_id;
  const history = new URLSearchParams();
  if (ids) history.set("ids", ids);
  if (resolvedPin) history.set("baseline", resolvedPin);

  return <>
    <div className="page-heading bar">
      <h1>Compare</h1>
      <div className="actions">
        <TimeToggle />
        <Link className="button" href={history.size ? `/runs?${history}` : "/runs"}>{ids ? "Change runs" : "Select runs"}</Link>
      </div>
    </div>
    {!ids ? <div className="empty"><h2>Select two to four succeeded runs</h2><p>Choose runs from your run history.</p></div> :
      selection.error ? <><Notice error={selection.error} /><button className="button" onClick={selection.reload}>Retry</button></> :
        !comparison ? <Pending>Loading comparison…</Pending> :
          <ComparisonView comparison={comparison} baseline={resolvedPin ?? comparison.runs[0].run_id} />}
  </>;
}

function ComparisonView({ comparison, baseline }: { comparison: Comparison; baseline: string }) {
  const runs = comparison.runs;
  const baselineIndex = runs.findIndex((run) => run.run_id === baseline);
  const order = [baselineIndex, ...runs.flatMap((_, index) => index === baselineIndex ? [] : [index])];
  const pairReasons = runs.map((_, index) => index === baselineIndex ? undefined : pairDifference(comparison, baselineIndex, index));
  const points = useMemo(() => {
    const byTime = new Map<string, PlotPoint>();
    for (const run of runs) {
      for (const point of run.curve) {
        const key = `${point.timestamp}:${point.phase}`;
        const values = byTime.get(key) ?? { timestamp: point.timestamp, phase: point.phase, equity: {}, drawdown: {} };
        values.equity[run.run_id] = point.value;
        values.drawdown[run.run_id] = point.drawdown;
        byTime.set(key, values);
      }
    }
    return [...byTime.values()];
  }, [runs]);

  function pin(id: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("baseline", id);
    window.history.pushState(null, "", url);
  }

  return <section className="comparison terminal-panel" aria-label="Backtest comparison">
    <div className="bar compare-alignment">
      <div>
        <h2>Chart alignment</h2>
        <p className="muted">
          {comparison.alignment === "exact" ? "Exact timestamps" :
            comparison.alignment === "intersection" ? "Common timestamps only" : "Overlay unavailable"}
          {comparison.display_window && <> · Chart window <Time value={comparison.display_window.from} /> – <Time value={comparison.display_window.to} /></>}
        </p>
      </div>
      <label className="inline-field">Baseline run
        <select value={baseline} onChange={(event) => pin(event.target.value)}>
          {runs.map((run) => <option key={run.run_id} value={run.run_id}>{runName(run)}</option>)}
        </select>
      </label>
    </div>
    {comparison.warnings.length > 0 && <div className="notice warning-text" role="status">
      {comparison.warnings.map((warning) => <p key={warning}>{warning}</p>)}
    </div>}
    <details className="disclosure comparison-inputs">
      <summary>Run inputs{comparison.differences.length > 0 &&
        ` · ${comparison.differences.map(({ field }) => labels[field] ?? title(field)).join(", ")} differ`}</summary>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Run inputs and differences">
        <table><thead><tr><th scope="col">Input</th>{order.map((index) => <th key={runs[index].run_id} scope="col">
          {runName(runs[index])}{index === baselineIndex && <span className="subline">Baseline</span>}
        </th>)}</tr></thead>
          <tbody>
            <tr><th scope="row">Full-run window</th>{order.map((index) => <td key={runs[index].run_id}>
              <Time value={String(runs[index].configuration.first_open ?? "")} /> – <Time value={String(runs[index].configuration.last_close_at ?? "")} />
            </td>)}</tr>
            <tr><th scope="row">Benchmark entry</th>{order.map((index) => <td key={runs[index].run_id}>
              <Time value={runs[index].benchmark_entry_at} />
            </td>)}</tr>
            {runs.some((run) => feedLabels(run.configuration.feeds).length > 0) &&
              <tr><th scope="row">Higher-timeframe feeds</th>{order.map((index) => <td key={runs[index].run_id}>
                {feedLabels(runs[index].configuration.feeds).join(", ") || "—"}
              </td>)}</tr>}
            {comparison.differences.filter(({ field }) => !["first_open", "last_close_at", "benchmark_entry_at"].includes(field))
              .map((difference) => <tr key={difference.field}>
                <th scope="row">{labels[difference.field] ?? title(difference.field)}
                  <span className="subline">{title(difference.severity)}</span>
                </th>
                {order.map((index) => <td key={runs[index].run_id}>{scalar(difference.values[index])}</td>)}
              </tr>)}
          </tbody></table>
      </div>
    </details>
    <div className="section comparison-results">
      <h2>Full-run metrics</h2>
      <MetricTable rows={headline} runs={runs} order={order} pairReasons={pairReasons} sourceLinks />
      {comparison.alignment !== "unavailable" && <EquityCharts points={points} unit="Index 100"
        series={runs.map((run) => ({
          id: run.run_id, label: runName(run) + (run.run_id === baseline ? " · Baseline" : ""), baseline: run.run_id === baseline,
        }))} />}
      <details className="disclosure">
        <summary>More full-run metrics</summary>
        <MetricTable rows={expanded} runs={runs} order={order} pairReasons={pairReasons} />
      </details>
    </div>
    <CommonWindow comparison={comparison} baseline={baseline} />
  </section>;
}

function CommonWindow({ comparison, baseline }: { comparison: Comparison; baseline: string }) {
  const { cohorts, pairs } = comparison.common_benchmark;
  const [selected, setSelected] = useState("");
  const preferred = cohorts.find((item) => item.run_ids.join(",") === selected) ??
    cohorts.find((item) => item.run_ids.includes(baseline)) ?? cohorts[0];
  const names = new Map(comparison.runs.map((run) => [run.run_id, runName(run)]));
  const unavailable = pairs.filter((pair) => pair.reason !== null);
  const series = preferred ? [
    { id: benchmarkId, label: "Buy-and-hold reference", baseline: true },
    ...preferred.strategies.filter((run) => !run.reason).map((run) => ({
      id: run.run_id, label: names.get(run.run_id) ?? run.run_id,
    })),
  ] : [];
  const points = useMemo(() => preferred?.points.map((point): PlotPoint => ({
    timestamp: point.timestamp, phase: point.phase,
    equity: { [benchmarkId]: point.benchmark, ...point.strategies },
    drawdown: {},
  })) ?? [], [preferred]);

  return <section className="section comparison-results" aria-label="Common-start benchmark">
    <div className="bar">
      <h2>Common-start benchmark</h2>
      {cohorts.length > 1 && <label className="inline-field">Run group
        <select value={preferred.run_ids.join(",")} onChange={(event) => setSelected(event.target.value)}>
          {cohorts.map((item) => <option key={item.run_ids.join(",")} value={item.run_ids.join(",")}>
            {item.run_ids.map((id) => names.get(id)).join(" / ")}
          </option>)}
        </select>
      </label>}
    </div>
    {preferred ? <>
      <p className="muted">Common window <Time value={preferred.start_at} /> to <Time value={preferred.end_at} /> ·
        Fee {numeric(preferred.fee_rate * 10000)} bps · Slippage {numeric(preferred.slippage_rate * 10000)} bps per side</p>
      <p>Each series starts at 100. Strategy positions already held at the common open are marked at that opening price.</p>
      <div className="table-wrap" tabIndex={0} role="region" aria-label="Common-window returns">
        <table><thead><tr><th scope="col">Series</th><th scope="col">Return</th><th scope="col">Excess over reference</th></tr></thead>
          <tbody>
            <tr><th scope="row">Buy-and-hold reference</th><td>{ratio(preferred.total_return)}</td><td>—</td></tr>
            {preferred.strategies.map((run) => <tr key={run.run_id}>
              <th scope="row">{names.get(run.run_id)}</th>
              <td>{run.reason ? "Unavailable" : ratio(run.total_return)}</td>
              <td>{run.excess_return == null ? "Unavailable" : `${numeric(run.excess_return * 100)} pp`}</td>
            </tr>)}
          </tbody>
        </table>
      </div>
      <EquityCharts points={points} series={series} unit="Common-window index" showDrawdown={false} dataLabel="Common-window chart data" />
    </> : <p>No common-start reference is available for these runs.</p>}
    {unavailable.length > 0 && <ul>
      {unavailable.map((pair) => <li key={pair.run_ids.join(",")}>
        {pair.run_ids.map((id) => names.get(id)).join(" / ")}. {pair.reason && benchmarkReasons[pair.reason]}
      </li>)}
    </ul>}
  </section>;
}

function MetricTable({ rows, runs, order, pairReasons, sourceLinks }: {
  rows: [string, Metric][]; runs: Comparison["runs"]; order: number[];
  pairReasons: (string | undefined)[]; sourceLinks?: boolean;
}) {
  const baseline = runs[order[0]];
  return <div className="table-wrap" tabIndex={0} role="region" aria-label={sourceLinks ? "Headline metrics" : "Additional metrics"}>
    <table className={runs.length === 2 ? "comparison-metrics two-run-metrics" : "comparison-metrics"}>
      <thead><tr><th scope="col">Metric</th>{order.map((index) => {
        const run = runs[index];
        const pinned = run === baseline;
        return <th key={run.run_id} scope="col" className={pinned ? "baseline-column" : undefined}>
          {sourceLinks ? <Link href={`/runs/${run.run_id}`}>{runName(run)}</Link> : runName(run)}
          {pinned && <span className="subline selection-label">Baseline</span>}
          {sourceLinks && <span className="subline">
            <Link href={`/strategies/${run.strategy_id}/revisions/${run.strategy_revision}`}>Strategy source</Link>
          </span>}
        </th>;
      })}</tr></thead>
      <tbody>{rows.map(([label, metric]) => <tr key={metric}><th scope="row">{label}</th>
        {order.map((index) => {
          const run = runs[index];
          const actual = metricValue(run, metric);
          const pinned = run === baseline;
          const delta = pinned ? undefined : metricDelta(baseline, run, metric, pairReasons[index]);
          const rendered = actual == null || !Number.isFinite(actual) ? "Unavailable" :
            metric === "final_equity" ? money(actual, typeof run.configuration.currency === "string" ? run.configuration.currency : undefined) :
              metric === "closed_trades" ? integer.format(actual) :
                metric === "sharpe" || metric === "profit_factor" ? numeric(actual) : ratio(actual);
          return <td key={run.run_id} className={pinned ? "baseline-column" : undefined}>
            <span className="numeric">{rendered}</span>
            <small className="metric-delta muted">
              {pinned ? <><span aria-hidden="true">—</span><span className="sr-only">Baseline delta</span></> :
                delta?.reason ? `Delta unavailable · ${delta.reason}` : <span className="numeric">{delta?.value}</span>}
            </small>
          </td>;
        })}
      </tr>)}</tbody>
    </table>
  </div>;
}
