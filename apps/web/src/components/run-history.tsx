"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { api, read } from "@/lib/api";
import type { components } from "@/lib/schema";
import { ratio, title } from "@/lib/format";
import { useResource } from "@/lib/use-resource";
import { Time, TimeToggle } from "./shell";
import { Notice, Pending } from "./ui";

type Run = components["schemas"]["RunSummary"];
const statuses = ["queued", "running", "succeeded", "failed", "cancelled"] as const;

export function RunHistory({ initialSelection, baseline }: { initialSelection: string[]; baseline?: string }) {
  const [strategy, setStrategy] = useState("");
  const [dataset, setDataset] = useState("");
  const [status, setStatus] = useState<Run["status"] | "">("");
  const [selection, setSelection] = useState(initialSelection);
  const [extra, setExtra] = useState<Run[]>([]);
  const [cursor, setCursor] = useState<string>();
  const [paging, setPaging] = useState(false);
  const [error, setError] = useState<unknown>();

  const list = useResource(useCallback(async (signal) => read(await api.GET("/api/v1/backtests", {
    params: { query: { strategy_id: strategy || undefined, dataset_id: dataset || undefined, status: status || undefined } }, signal,
  })), [strategy, dataset, status]));
  const filters = useResource(useCallback(async (signal) => {
    const [strategies, datasets] = await Promise.all([
      api.GET("/api/v1/strategies", { params: { query: { limit: 500 } }, signal }),
      api.GET("/api/v1/datasets", { params: { query: { limit: 500 } }, signal }),
    ]);
    return { strategies: read(strategies).items, datasets: read(datasets).items };
  }, []));
  const selected = useResource(useCallback(async (signal) =>
    Promise.all(selection.map(async (ident) => read(await api.GET("/api/v1/backtests/{ident}", {
      params: { path: { ident } }, signal,
    })))), [selection]));
  const rows = [...(list.data?.items ?? []), ...extra];
  const next = extra.length ? cursor : list.data?.next_cursor;
  const ready = selected.data?.length === selection.length && selection.length >= 2 &&
    selected.data.every((run, index) => run.status === "succeeded" && run.id === selection[index]);

  const compareQuery = new URLSearchParams({ ids: selection.join(",") });
  if (baseline && selection.includes(baseline)) compareQuery.set("baseline", baseline);

  async function loadMore() {
    if (!next || paging) return;
    setPaging(true);
    setError(undefined);
    try {
      const page = read(await api.GET("/api/v1/backtests", {
        params: { query: { cursor: next, strategy_id: strategy || undefined, dataset_id: dataset || undefined, status: status || undefined } },
      }));
      setExtra((previous) => [...previous, ...page.items]);
      setCursor(page.next_cursor ?? undefined);
    } catch (cause) {
      setError(cause);
    } finally {
      setPaging(false);
    }
  }

  return <>
    <div className="page-heading bar"><h1>Runs</h1><TimeToggle /></div>
    <div className="bar section-heading">
      <div className="actions history-filters">
        <label className="stack-field">Strategy
          <select value={strategy} onChange={(event) => { setStrategy(event.target.value); setExtra([]); }}>
            <option value="">All strategies</option>
            {filters.data?.strategies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </label>
        <label className="stack-field">Dataset
          <select value={dataset} onChange={(event) => { setDataset(event.target.value); setExtra([]); }}>
            <option value="">All datasets</option>
            {filters.data?.datasets.map((item) => <option key={item.id} value={item.id}>{item.filename}</option>)}
          </select>
        </label>
        <label className="stack-field">Status
          <select value={status} onChange={(event) => { setStatus(event.target.value as typeof status); setExtra([]); }}>
            <option value="">All statuses</option>
            {statuses.map((item) => <option key={item} value={item}>{title(item)}</option>)}
          </select>
        </label>
      </div>
      {ready ? <Link className="button primary" href={`/compare?${compareQuery}`}>Compare {selection.length} runs</Link>
        : <button className="button primary" disabled>Compare runs</button>}
    </div>
    <Notice error={error ?? list.error ?? filters.error} />
    {(list.error || filters.error) && <button className="button" onClick={() => { list.reload(); filters.reload(); }}>Retry</button>}
    <div className="workspace">
      <section aria-label="Run history">
        {!list.error && !list.data ? <div className="empty"><Pending /></div> :
          rows.length ? <div className="table-wrap library-table" tabIndex={0} role="region" aria-label="Run history table">
            <table><thead><tr><th scope="col"><span className="sr-only">Select run</span></th>
              <th>Strategy</th><th>Dataset</th><th>Status</th><th>Submitted</th><th className="number">Return</th></tr></thead>
              <tbody>{rows.map((run) => <tr key={run.id} className={selection.includes(run.id) ? "selected" : ""}>
                <td><input type="checkbox" aria-label={`Select ${run.strategy_name} revision ${run.strategy_revision} for comparison`}
                  checked={selection.includes(run.id)}
                  disabled={run.status !== "succeeded" || (!selection.includes(run.id) && selection.length >= 4)}
                  onChange={(event) => setSelection((current) =>
                    event.target.checked ? [...current, run.id] : current.filter((id) => id !== run.id))} /></td>
                <td><Link href={`/runs/${run.id}`}>{run.strategy_name}</Link><span className="subline">Revision {run.strategy_revision}</span></td>
                <td>{run.dataset_name}</td><td>{title(run.status)}</td><td><Time value={run.created_at} /></td>
                <td className="numeric number">{run.headline ? ratio(run.headline.total_return) : "—"}</td>
              </tr>)}</tbody>
            </table>
            {next && <div className="table-actions"><button className="button compact" disabled={paging} onClick={loadMore}>Load more</button></div>}
          </div> : list.data && <div className="empty">
            <h2>{strategy || dataset || status ? "No matching runs" : "No backtests yet"}</h2>
            <Link href="/strategies">Open strategies</Link>
          </div>}
      </section>
      <aside className="inspector">
        <h2>Selected runs</h2>
        <p className="muted">Select 2–4 succeeded runs.</p>
        <Notice error={selected.error} />
        {selection.length > 0 && Boolean(selected.error) && <button className="text-button" onClick={() => setSelection([])}>Clear selection</button>}
        <ul className="diagnostics">{selection.map((id) => {
          const run = selected.data?.find((item) => item.id === id) ?? rows.find((item) => item.id === id);
          return <li key={id} className="bar">
            <div><strong>{run?.strategy_name ?? "Selected run"}</strong>
              {run && <span className="subline">Revision {run.strategy_revision}</span>}
            </div>
            <button className="text-button" aria-label={`Remove ${run?.strategy_name ?? "run"}`}
              onClick={() => setSelection((current) => current.filter((value) => value !== id))}>Remove</button>
          </li>;
        })}</ul>
      </aside>
    </div>
  </>;
}
