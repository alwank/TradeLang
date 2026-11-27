"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState, type FormEvent } from "react";
import { accepted, api, read, type Strategy } from "@/lib/api";
import catalog from "@/lib/catalog.json";
import { title } from "@/lib/format";
import { useResource } from "@/lib/use-resource";
import { Time, TimeToggle } from "./shell";
import { Details, Notice, Pending } from "./ui";

export function StrategyLibrary() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string>();
  const [extra, setExtra] = useState<Strategy[]>([]);
  const [cursor, setCursor] = useState<string>();
  const [creating, setCreating] = useState(false);
  const [template, setTemplate] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const list = useResource(useCallback(async (signal) => read(await api.GET("/api/v1/strategies", {
    params: { query: { q: query || undefined } }, signal,
  })), [query]));
  const rows = [...(list.data?.items ?? []), ...extra];
  const current = rows.find((row) => row.id === selected) ?? rows[0];
  const next = extra.length ? cursor : list.data?.next_cursor;

  async function mutate(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError(undefined);
    try {
      await action();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function create(name: string, source: string) {
    const result = read(await api.POST("/api/v1/strategies", { body: { name, source } }));
    router.push(`/strategies/${result.id}`);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const source = catalog.examples.find((example) => example.name === template)?.source ?? "";
    void mutate(() => create(name.trim(), source));
  }

  return <>
    <div className="page-heading"><h1>Strategies</h1></div>
    <div className="bar section-heading">
      <form className="inline-field" onSubmit={(event) => {
        event.preventDefault();
        setQuery(search.trim());
        setExtra([]);
        setSelected(undefined);
      }}>
        <input className="strategy-search" aria-label="Search strategies" placeholder="Search strategies" value={search}
          onChange={(event) => setSearch(event.target.value)} />
        <button className="button">Search</button>
      </form>
      <div className="actions">
        <TimeToggle />
        <button className="button primary" onClick={() => {
          setCreating(true);
          setTemplate("");
          setName("");
          setError(undefined);
        }}>New strategy</button>
      </div>
    </div>
    <Notice error={error ?? list.error} />
    {list.error && <button className="button" onClick={list.reload}>Retry</button>}
    {!list.error && !list.data && <Pending />}
    <div className="workspace">
      <section aria-label="Strategy library">
        {rows.length ? <div className="table-wrap library-table" tabIndex={0} role="region" aria-label="Strategies table">
          <table><thead><tr>
            <th>Strategy</th><th>Revision</th><th>Updated</th><th>Last run</th>
          </tr></thead><tbody>
            {rows.map((row) => {
              const sourceName = /^\s*strategy\s+"([^"\n]+)"/m.exec(row.current_source)?.[1];
              return <tr key={row.id} className={row.id === current?.id ? "selected" : ""}>
                <td><button className="text-button" aria-pressed={row.id === current?.id} onClick={() => {
                  setSelected(row.id);
                  setCreating(false);
                }}>{row.name}</button>
                  {sourceName && sourceName !== row.name && <span className="subline">{sourceName}</span>}
                </td>
                <td className="numeric">{row.current_revision}</td><td><Time value={row.updated_at} /></td>
                <td>{row.last_run_status ? title(row.last_run_status) : "No runs"}</td>
              </tr>;
            })}
          </tbody></table>
          {next && <div className="table-actions"><button className="button compact" disabled={busy} onClick={() => {
            void mutate(async () => {
              const page = read(await api.GET("/api/v1/strategies", { params: { query: { cursor: next, q: query || undefined } } }));
              setExtra((previous) => [...previous, ...page.items]);
              setCursor(page.next_cursor ?? undefined);
            });
          }}>Load more</button></div>}
        </div> : list.data && <div className="empty">
          <h2>{query ? "No matching strategies" : "No strategies yet"}</h2>
          {!query && <p>Start with a blank draft or open a complete example.</p>}
        </div>}
      </section>
      <aside className="inspector" aria-label={creating ? "New strategy" : "Strategy details"}>
        {creating ? <form onSubmit={submit}>
          <h2>New strategy</h2>
          <div className="form-grid" style={{ gridTemplateColumns: "1fr" }}>
            <label>Start from
              <select value={template} onChange={(event) => {
                setTemplate(event.target.value);
                if (event.target.value) setName(event.target.value);
              }}>
                <option value="">Blank draft</option>
                {catalog.examples.map((example) => <option key={example.name}>{example.name}</option>)}
              </select>
            </label>
            <label>Strategy name<input autoFocus required maxLength={120} value={name}
              onChange={(event) => setName(event.target.value)} /></label>
          </div>
          <div className="actions">
            <button className="button" type="button" disabled={busy} onClick={() => setCreating(false)}>Cancel</button>
            <button className="button primary" disabled={busy || !name.trim()}>Create strategy</button>
          </div>
        </form> : current && <>
          <h2>{current.name}</h2>
          <Details rows={[
            ["Current revision", current.current_revision], ["Updated", <Time key="time" value={current.updated_at} />],
            ["Last run", current.last_run_status ? title(current.last_run_status) : "No runs"],
          ]} />
          <Link className="button stretch" href={`/strategies/${current.id}`}>Open editor</Link>
          <div className="actions">
            <button className="text-button" disabled={busy} onClick={() => void mutate(() =>
              create(`${current.name.slice(0, 115)} copy`, current.current_source))}>Duplicate</button>
            <button className="text-button danger" disabled={busy} onClick={() => {
              if (!window.confirm("Archive this strategy from the active library? Saved run snapshots remain available.")) return;
              void mutate(async () => {
                accepted(await api.DELETE("/api/v1/strategies/{ident}", {
                  params: { path: { ident: current.id }, header: { "If-Match": current.etag } },
                }));
                setExtra([]);
                setSelected(undefined);
                list.reload();
              });
            }}>Archive</button>
          </div>
        </>}
      </aside>
    </div>
  </>;
}
