"use client";

import { useId, useMemo, useState, type ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { numeric, ratio } from "@/lib/format";
import { Time, useDisplayTime } from "./shell";

export type Series = { id: string; label: string; baseline?: boolean };
export type PlotPoint = {
  timestamp: string;
  phase: "initial" | "close" | "mark";
  equity: Record<string, number>;
  drawdown: Record<string, number>;
};

const colors = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)", "var(--ink)"];
const strokes = ["11 4", "7 4", "3 3", "9 3 2 3", "2 4"];

export function EquityCharts({ points, series, unit, controls, showDrawdown = true, dataLabel = "Chart data" }: {
  points: PlotPoint[]; series: Series[]; unit: string; controls?: ReactNode; showDrawdown?: boolean; dataLabel?: string;
}) {
  const id = useId();
  const comparison = series.some((line) => line.baseline);
  const strokeFor = (line: Series, index: number) => (comparison ? line.baseline : index === 0) ? undefined : strokes[index];
  const local = useDisplayTime();
  const [table, setTable] = useState(false);
  const [page, setPage] = useState(0);
  const layouts = useMemo(() => points.map((point) => ({
    ...point,
    x: Date.parse(point.timestamp),
  })), [points]);
  const first = layouts[0]?.x ?? 0;
  const last = layouts.at(-1)?.x ?? 0;
  const span = last - first;
  const ticks = [...new Set(Array.from({ length: 5 }, (_, index) => first + (span * index) / 4))];
  const shortDate = new Intl.DateTimeFormat("en", span < 7 * 86400000
    ? { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: local ? undefined : "UTC" }
    : { month: "short", day: "numeric", year: "2-digit", timeZone: local ? undefined : "UTC" });
  const longDate = new Intl.DateTimeFormat("en", {
    dateStyle: "long", timeStyle: "medium", timeZone: local ? undefined : "UTC",
  });
  const visiblePage = Math.min(page, Math.max(0, Math.ceil(points.length / 20) - 1));

  function chart(metric: "equity" | "drawdown") {
    const isRatio = metric === "drawdown";
    const label = isRatio ? "Drawdown" : `Equity · ${unit}`;
    return <section className="chart" aria-label={label}>
      <h3>{label}</h3>
      <ResponsiveContainer width="100%" height={isRatio ? 118 : 174} minWidth={0}>
        <LineChart data={layouts} syncId={id} syncMethod="index" accessibilityLayer
          margin={{ left: 0, right: 18, top: 8, bottom: 0 }}>
          <CartesianGrid stroke="var(--border)" />
          <XAxis dataKey="x" type="number" scale="time" domain={["dataMin", "dataMax"]}
            tickFormatter={(value) => shortDate.format(value)} tick={{ fill: "var(--muted)", fontSize: 11 }}
            ticks={ticks} hide={showDrawdown && !isRatio} minTickGap={20} />
          <YAxis width={72} tickFormatter={(value) => isRatio ? ratio(value) : numeric(value)}
            tick={{ fill: "var(--muted)", fontSize: 11 }} />
          <Tooltip contentStyle={{ background: "var(--inspector)", borderColor: "var(--control-border)", color: "var(--ink)" }}
            labelFormatter={(value) => `${longDate.format(Number(value))}${local ? "" : " UTC"}`}
            formatter={(value) => isRatio ? ratio(Number(value)) : numeric(Number(value))} />
          {series.map((line, index) => <Line key={line.id} dataKey={(point: PlotPoint) => point[metric][line.id]}
            name={line.label} type="linear" connectNulls={false} stroke={colors[index]}
            strokeDasharray={strokeFor(line, index)} strokeWidth={line.baseline ? 2.6 : 2} dot={false} isAnimationActive={false} />)}
        </LineChart>
      </ResponsiveContainer>
    </section>;
  }

  if (!points.length) return null;
  return <>
    <ul className="series-legend" aria-label="Chart series">
      {series.map((line, index) => <li key={line.id}>
        <svg aria-hidden="true" width="24" height="8" viewBox="0 0 24 8">
          <path d="M0 4h24" stroke={colors[index]} strokeDasharray={strokeFor(line, index)} strokeWidth={line.baseline ? 2.6 : 2} />
        </svg>
        {line.label}
      </li>)}
    </ul>
    {chart("equity")}
    {showDrawdown && chart("drawdown")}
    <div className="chart-controls">
    <details className={table ? "disclosure chart-data-open" : "disclosure"} onToggle={(event) => setTable(event.currentTarget.open)}>
      <summary>{showDrawdown ? "View chart data" : "View common-window chart data"}</summary>
      {table && <div className="table-wrap" tabIndex={0} role="region" aria-label={dataLabel}>
        <table><thead><tr><th>Time</th><th>Phase</th>
          {series.map((line) => <th key={line.id}>{line.label}</th>)}
        </tr></thead><tbody>
          {points.slice(visiblePage * 20, (visiblePage + 1) * 20).map((point) =>
            <tr key={`${point.timestamp}-${point.phase}`}>
              <td><Time value={point.timestamp} /></td><td>{point.phase}</td>
              {series.map((line) => <td className="numeric" key={line.id}>
                {numeric(point.equity[line.id])}{showDrawdown && <> · {ratio(point.drawdown[line.id])}</>}
              </td>)}
            </tr>)}
        </tbody></table>
        {points.length > 20 && <div className="actions table-actions">
          <button className="button compact" disabled={visiblePage === 0} onClick={() => setPage(visiblePage - 1)}>Previous page</button>
          <button className="button compact" disabled={(visiblePage + 1) * 20 >= points.length} onClick={() => setPage(visiblePage + 1)}>Next page</button>
        </div>}
      </div>}
    </details>
    {controls}
    </div>
  </>;
}
