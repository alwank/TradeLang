"use client";

import { useCallback, useState, type FormEvent } from "react";
import { api, read } from "@/lib/api";
import { money, numeric, title } from "@/lib/format";
import type { components } from "@/lib/schema";
import { useResource } from "@/lib/use-resource";
import { Time } from "./shell";
import { Details, Notice, Pending } from "./ui";

type Trace = components["schemas"]["ExpressionTrace"];
type Rule = components["schemas"]["RuleInspection"];

const outcomes: Record<string, string> = {
  warmup: "Waiting for warmup",
  post_exit: "Skipped after an exit on this candle",
  holding: "Blocked while holding a position",
  flat: "Already flat",
  exit_priority: "Exit rule took priority",
  entry_rejected: "Entry rejected",
  exit_rejected: "Exit rejected",
  order_queued: "Order queued",
  order_expired_end: "Order expired at the end of the window",
  false: "Condition was false",
  unavailable: "Condition unavailable",
};

const reasons: Record<string, string> = {
  inspection_not_recorded: "This run predates candle inspection.",
  inspection_runtime_mismatch: "Expression samples require the runtime recorded in this run.",
  inspection_work_limit: "Rebuilding the expression samples exceeds the inspection limit.",
  inspection_busy: "Another candle inspection is in progress.",
};

const orderedOutcomes: Record<components["schemas"]["OrderedExitInspection"]["outcome"], string> = {
  selected: "Triggered exit",
  exit_priority: "Blocked entry while flat",
  false: "Condition was false",
  unavailable: "Condition unavailable",
  skipped: "Skipped after an earlier rule matched",
};

function TraceValues({ label, trace }: { label: string; trace: Trace }) {
  return <details className="disclosure">
    <summary>{label}</summary>
    <div className="table-scroll">
      <table>
        <thead><tr><th>Expression</th><th>Source</th><th>Bar</th><th>Observed at</th><th>Value</th></tr></thead>
        <tbody>{trace.samples.map((sample, index) => <tr key={index}>
          <td><code>{sample.node_id}{sample.field ? ` · ${sample.field}` : ""}</code>
            {sample.feed && <small className="subline">Feed {sample.feed} · {sample.clock} clock</small>}
            {sample.definition_node_id && <small className="subline">From {sample.definition_node_id}</small>}</td>
          <td>{sample.span.start_line}:{sample.span.start_column}</td>
          <td>{sample.bar_index ?? "—"}</td>
          <td>{sample.observed_at ? <Time value={sample.observed_at} /> : "—"}</td>
          <td>{sample.available ? `${String(sample.value)}${sample.unit ? ` ${sample.unit}` : ""}`
            : title(sample.unavailable_reason ?? "unavailable")}</td>
        </tr>)}</tbody>
      </table>
    </div>
    {trace.truncated && <p className="muted">The sample limit was reached.</p>}
  </details>;
}

function ruleText(rule: Rule) {
  const outcome = outcomes[rule.outcome] ?? title(rule.outcome);
  return rule.predicate === true ? `True · ${outcome}` : outcome;
}

export function BarInspector({ runId, index, currency, totalBars, inspect, asset }: {
  runId: string; index: number | null; currency: string; totalBars?: number;
  inspect: (index: number) => void; asset?: string;
}) {
  const [input, setInput] = useState(index === null ? "" : String(index));
  const result = useResource(useCallback(async (signal) => index === null ? undefined : read(await api.GET(
    "/api/v1/backtests/{ident}/bars/{index}",
    { params: { path: { ident: runId, index }, query: { asset } }, signal },
  )), [runId, index, asset]));
  const bar = result.data;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const value = Number(input);
    if (input && Number.isSafeInteger(value) && value >= 0) inspect(value);
  };
  return <section className="section" aria-label="Candle decision">
    <h2>Candle decision</h2>
    <form className="actions" onSubmit={submit}>
      <label className="inline-field">Dataset bar index
        <input type="number" min={0} step={1} value={input} onChange={(event) => setInput(event.target.value)} required />
      </label>
      <button className="button compact">Inspect candle</button>
    </form>
    <p className="muted">{asset
      ? "Use a zero-based index from the selected asset's dataset within its execution window."
      : `Indices start at 0 in the primary dataset. This run covers ${totalBars} observed candles.`}</p>
    <Notice error={result.error} />
    {index !== null && !bar && !result.error && <Pending>Inspecting candle…</Pending>}
    {bar?.reason && <p role="status">{reasons[bar.reason] ?? title(bar.reason)}
      {bar.reason === "inspection_busy" && <button className="text-button" onClick={result.reload}>Retry</button>}</p>}
    {bar?.entry && bar.exit && <>
      <Details rows={[
        ["Open", bar.bar_open_at && <Time value={bar.bar_open_at} />],
        ["Close", bar.close_at && <Time value={bar.close_at} />],
        ...(bar.split_factor != null ? [["Shares per reference unit", numeric(bar.split_factor)] as [string, string]] : []),
        ["Entry", ruleText(bar.entry)], ["Exit", ruleText(bar.exit)],
      ]} />
      {bar.entry.expression && <TraceValues label="Entry expression samples" trace={bar.entry.expression} />}
      {bar.exit.expression && <TraceValues label="Exit expression samples" trace={bar.exit.expression} />}
      {bar.sale_expression && <TraceValues label="Exit size samples" trace={bar.sale_expression} />}
      {bar.scale_expression && <TraceValues label="Scale condition samples" trace={bar.scale_expression} />}
      {bar.add_sizing && <TraceValues label="Add size samples" trace={bar.add_sizing} />}
      {bar.exit_rules.length > 0 && <details className="disclosure"><summary>Ordered exit rules</summary>
        <Details rows={[["Completed holding candles", bar.holding_closes]]} />
        <ol>{bar.exit_rules.map((rule) => <li key={rule.name}>
          <div><code>{rule.name}</code> · {orderedOutcomes[rule.outcome]}</div>
          {rule.after_bars != null && <div>Exit after {rule.after_bars} completed holding candles</div>}
          {rule.expression && <TraceValues label={`${rule.name} expression samples`} trace={rule.expression} />}
          {rule.sale_expression && <TraceValues label={`${rule.name} size samples`} trace={rule.sale_expression} />}
        </li>)}</ol>
      </details>}
      {bar.trail_expression && <TraceValues label="Trailing stop samples" trace={bar.trail_expression} />}
      {bar.trail_updates.length > 0 && <details className="disclosure"><summary>Trailing stop changes</summary>
        {bar.trail_updates.map((step) => <Details key={`${step.sampled_bar}:${step.effective_open_at ?? "queued"}`} rows={[
          ["Status", step.effective_open_at ? "Active at this open" : "Queued for next open"],
          ["Sampled close", <Time value={step.sampled_at} />],
          ["Effective open", step.effective_open_at && <Time value={step.effective_open_at} />],
          ["Previous trigger", money(step.previous_trigger_price, currency)],
          ["New trigger", money(step.trigger_price, currency)],
        ]} />)}
      </details>}
      {Object.entries(bar.entry_inputs).map(([name, trace]) =>
        <TraceValues key={name} label={`Signal-close ${name} samples`} trace={trace} />)}
      {bar.entry_fill && <>
        <Details rows={[
          ["Signal bar", <button className="text-button" onClick={() => inspect(bar.entry_fill!.signal_bar)}>
            {bar.entry_fill.signal_bar}</button>],
          ["Cash before fill", money(bar.entry_fill.cash, currency)],
          ["Sizing result", numeric(bar.entry_fill.sizing_value)],
          [bar.risk_sizing ? "Risk budget" : "Requested budget", money(bar.entry_fill.budget, currency)],
        ]} />
        <TraceValues label="Entry sizing samples" trace={bar.entry_fill.expression} />
        {bar.entry_fill.allocation_expression &&
          <TraceValues label="Allocation cap samples" trace={bar.entry_fill.allocation_expression} />}
        {bar.entry_fill.protection && Object.values(bar.entry_fill.protection).some(Boolean) &&
          <details className="disclosure"><summary>Protection established at the fill</summary>
            <pre className="audit-values">{JSON.stringify(bar.entry_fill.protection, null, 2)}</pre>
          </details>}
      </>}
      {bar.risk_sizing && <details className="disclosure"><summary>Stop-based sizing</summary>
        <Details rows={[
          ["Risk budget", money(bar.risk_sizing.risk_budget, currency)],
          ["Cash available", money(bar.risk_sizing.cash_available, currency)],
          ["Allocation limit", money(bar.risk_sizing.allocation_limit, currency)],
          ["Opening reference", numeric(bar.risk_sizing.entry_open)],
          ["Entry fill price", numeric(bar.risk_sizing.entry_fill_price)],
          ["Stop trigger", numeric(bar.risk_sizing.stop_trigger_price)],
          ["Modeled stop fill", numeric(bar.risk_sizing.modeled_stop_fill_price)],
          ["Modeled loss per unit", numeric(bar.risk_sizing.loss_per_unit)],
          ["Modeled loss", money(bar.risk_sizing.modeled_loss, currency)],
          ["Entry debit", money(bar.risk_sizing.entry_debit, currency)],
          ["Final quantity", numeric(bar.risk_sizing.quantity)],
          ["Binding constraint", title(bar.risk_sizing.binding_constraint)],
          ["Rounding", bar.risk_sizing.rounded_down ? "Quantity rounded down" : null],
        ]} />
      </details>}
      {!!bar.events.length && <details className="disclosure"><summary>Candle events</summary>
        <ul>{bar.events.map((event) => <li key={event.event_id}>
          <strong>{title(event.kind)} · {title(event.reason)}</strong>
          <div>{event.event_id}{event.order_id ? ` · ${event.order_id}` : ""}
            {event.fill_id ? ` · ${event.fill_id}` : ""} · <Time value={event.observed_at} /></div>
          {event.kind === "fill" && ["short", "cover"].includes(String(event.data.side)) &&
            <div>{title(String(event.data.side))} · {numeric(Number(event.data.quantity_after))} units remaining</div>}
          {event.kind === "borrow_charged" && typeof event.data.borrow_cost === "number" &&
            <div>{money(event.data.borrow_cost, currency)} over {numeric(Number(event.data.elapsed_seconds))} seconds</div>}
          {typeof event.data.maintenance_trigger === "number" &&
            <div>Maintenance trigger {money(event.data.maintenance_trigger, currency)}</div>}
          {event.kind === "order_expired_stale" && typeof event.data.age_seconds === "number" &&
            typeof event.data.max_age_seconds === "number" &&
            <div>{numeric(event.data.age_seconds)} seconds old · limit {numeric(event.data.max_age_seconds)} seconds</div>}
        </li>)}</ul>
      </details>}
    </>}
  </section>;
}
