"use client";

import Link from "next/link";
import { useCallback, useState, type FormEvent } from "react";
import { api, read, upload, type Dataset } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { Details, Notice, Pending } from "./ui";
import { Time } from "./shell";

const number = new Intl.NumberFormat("en", { maximumFractionDigits: 8 });
const maxBytes = 100 * 1024 * 1024;

export function DatasetLibrary({ strategyId }: { strategyId?: string }) {
  const [selected, setSelected] = useState<string>();
  const [importing, setImporting] = useState(false);
  const [choosing, setChoosing] = useState(false);
  const [importMessage, setImportMessage] = useState("");
  const [cursor, setCursor] = useState<string>();
  const [extra, setExtra] = useState<Dataset[]>([]);
  const [pageError, setPageError] = useState<unknown>();
  const [paging, setPaging] = useState(false);
  const list = useResource(useCallback(async (signal) =>
    read(await api.GET("/api/v1/datasets", { signal })), []));
  const rows = [...(list.data?.items ?? []), ...extra];
  const id = selected ?? rows[0]?.id;
  const detail = useResource(useCallback(async (signal) => id
    ? read(await api.GET("/api/v1/datasets/{ident}", { params: { path: { ident: id } }, signal }))
    : undefined, [id]));
  const strategies = useResource(useCallback(async (signal) => choosing
    ? read(await api.GET("/api/v1/strategies", { signal }))
    : undefined, [choosing]));
  const next = extra.length > 0 ? cursor : list.data?.next_cursor;

  async function page() {
    if (!next || paging) return;
    setPaging(true);
    setPageError(undefined);
    try {
      const response = read(await api.GET("/api/v1/datasets", { params: { query: { cursor: next } } }));
      setExtra((previous) => [...previous, ...response.items]);
      setCursor(response.next_cursor ?? undefined);
    } catch (cause) {
      setPageError(cause);
    } finally {
      setPaging(false);
    }
  }

  if (importing) return <ImportDataset cancel={() => setImporting(false)} onDone={(result) => {
    setImporting(false);
    setSelected(result.dataset.id);
    setChoosing(false);
    setExtra([]);
    setImportMessage(result.deduplicated
      ? "This file and metadata match an existing import. The existing dataset has been selected."
      : "Dataset imported.");
    list.reload();
  }} />;

  const dataset = detail.data?.id === id ? detail.data : undefined;
  return (
    <>
      <div className="page-heading bar">
        <div className="heading-copy">
          <h1>Datasets</h1>
          <p className="muted">CSV or Parquet · up to 100 MiB and 1,000,000 rows</p>
        </div>
        <button className="button primary" onClick={() => setImporting(true)}>Import dataset</button>
      </div>
      {importMessage && <p className="notice" role="status">{importMessage}</p>}
      {list.error ? <><Notice error={list.error} /><button className="button" onClick={list.reload}>Retry</button></> :
        !list.data ? <Pending /> :
        <div className="workspace">
          <section aria-label="Dataset library">
            {rows.length > 0 ? (
              <div className="table-wrap library-table" tabIndex={0} role="region" aria-label="Datasets table">
                <table><thead><tr>
                  <th>Dataset</th><th>Market</th><th>Timeframe</th>
                  <th className="number">Candles</th><th>Range</th>
                </tr></thead><tbody>
                  {rows.map((row) => <tr key={row.id} className={row.id === id ? "selected" : ""}>
                    <td><button className="text-button" onClick={() => {
                      setSelected(row.id);
                      setChoosing(false);
                    }} aria-pressed={row.id === id}>{row.filename}</button></td>
                    <td>{row.metadata.symbol}</td><td>{row.metadata.timeframe}</td>
                    <td className="number numeric">{number.format(row.row_count)}</td>
                    <td><Time dateOnly value={row.first_open} /> – <Time dateOnly value={row.last_open} /></td>
                  </tr>)}
                </tbody></table>
                <Notice error={pageError} />
                {next && <div className="table-actions">
                  <button className="button compact" disabled={paging} onClick={page}>Load more</button>
                </div>}
              </div>
            ) : <div className="empty">
              <h2>No datasets yet</h2>
              <p>Import completed spot candles with open timestamps and base-quantity volume.</p>
            </div>}
            {dataset && <section className="section">
              <h2>First and last candles</h2>
              <div className="table-wrap" tabIndex={0} role="region" aria-label="Candle preview">
                <table><thead><tr><th>Open time</th>{["Open", "High", "Low", "Close", "Volume"].map((name) =>
                  <th key={name} className="number">{name}</th>)}</tr></thead>
                  <tbody>{dataset.preview.filter((_, index, samples) =>
                    index === 0 || index === samples.length - 1).map((row) => <tr key={row.row}>
                    <td><Time value={row.timestamp} /></td>
                    {[row.open, row.high, row.low, row.close, row.volume].map((value, index) =>
                      <td key={index} className="numeric number">{number.format(value)}</td>)}
                  </tr>)}</tbody>
                </table>
              </div>
            </section>}
          </section>
          <aside className="inspector" aria-label="Dataset details">
            <Notice error={detail.error} />
            {detail.error ? <button className="button compact" onClick={detail.reload}>Retry</button> :
              id && !dataset && <Pending>Loading dataset…</Pending>}
            {dataset && <>
              <h2>{dataset.filename}</h2>
              <p className="muted">{dataset.metadata.symbol} · {dataset.metadata.timeframe}</p>
              <Details rows={[
                ["Quote currency", dataset.metadata.quote_currency],
                ["Calendar", dataset.metadata.session_schedule
                  ? `${dataset.metadata.session_schedule.market} · ${dataset.metadata.session_schedule.version} · ${dataset.metadata.session_schedule.timezone}`
                  : "24×7"],
                ["Timestamp", "Bar open (UTC)"],
                ["Price basis", { raw_spot: "Raw spot", raw_equity: "Raw equity", split_reference: "Split reference" }[dataset.metadata.price_basis]],
                ["Volume unit", "Base quantity"],
                ["Gap policy", dataset.metadata.gap_policy === "allow" ? "Allow gaps" : "Reject gaps"],
                ["Fingerprint", <details className="fingerprint" key="hash">
                  <summary>Show full fingerprint</summary>
                  <code>{dataset.dataset_hash}</code>
                </details>],
              ]} />
              <p>{dataset.quality.missing_bar_count
                ? `${number.format(dataset.quality.missing_bar_count)} missing candles`
                : "No missing candles"}</p>
              {dataset.warnings.length > 0 && <ul>{dataset.warnings.map((warning, index) =>
                <li key={index}>{warning.message}</li>)}</ul>}
              <div className="actions">
                {strategyId ? <Link className="button stretch" href={editorLink(strategyId, dataset.id)}>
                  Select in editor
                </Link> : <button className="button stretch" onClick={() => setChoosing((value) => !value)}
                  aria-expanded={choosing}>Select in editor</button>}
              </div>
              {choosing && <div className="section">
                <Notice error={strategies.error} />
                {Boolean(strategies.error) && <button className="button compact" onClick={strategies.reload}>Retry strategies</button>}
                {!strategies.error && !strategies.data && <Pending />}
                {strategies.data?.items.length === 0 && <Link href="/strategies">Create a strategy</Link>}
                {strategies.data?.items.map((strategy) => <p key={strategy.id}>
                  <Link href={editorLink(strategy.id, dataset.id)}>{strategy.name}</Link>
                </p>)}
              </div>}
            </>}
          </aside>
        </div>}
    </>
  );
}

function editorLink(strategy: string, dataset: string) {
  return `/strategies/${encodeURIComponent(strategy)}?dataset=${encodeURIComponent(dataset)}`;
}

function ImportDataset({
  cancel, onDone,
}: { cancel: () => void; onDone: (result: Awaited<ReturnType<typeof upload>>) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [hasMetadata, setHasMetadata] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setError(undefined);
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || !file.name) {
      setError(new Error("Choose a candle file."));
      return;
    }
    if (file.size > maxBytes) {
      setError(new Error("The file exceeds 100 MiB."));
      return;
    }
    const body = new FormData();
    body.set("file", file);
    const metadata = form.get("metadata-file");
    setBusy(true);
    try {
      if (metadata instanceof File && metadata.name && metadata.size > 2 * 1024 ** 2) {
        throw new Error("The metadata file exceeds 2 MiB.");
      }
      body.set("metadata", metadata instanceof File && metadata.name ? await metadata.text() : JSON.stringify({
        symbol: String(form.get("symbol")).trim(),
        quote_currency: String(form.get("currency")).trim(),
        timeframe: String(form.get("timeframe")).trim(),
        calendar: "24x7",
        timestamp_convention: "bar_open",
        price_basis: "raw_spot",
        volume_unit: "base_quantity",
        gap_policy: form.get("gap"),
      }));
      onDone(await upload(body));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  return <>
    <div className="page-heading"><h1>Import dataset</h1></div>
    <div className="workspace">
      <form className="section" onSubmit={submit}>
        <label className="stack-field">File
          <input name="file" type="file" accept=".csv,.parquet" required aria-describedby="file-limits" />
        </label>
        <p id="file-limits" className="muted">CSV or Parquet · up to 100 MiB and 1,000,000 rows</p>
        <label className="stack-field">Metadata JSON
          <input name="metadata-file" type="file" accept=".json,application/json"
            onChange={(event) => setHasMetadata(Boolean(event.currentTarget.files?.length))} />
        </label>
        {!hasMetadata && <><div className="form-grid">
          <label>Symbol<input required maxLength={32} name="symbol" placeholder="BTCUSDT" /></label>
          <label>Quote currency<input required maxLength={12} name="currency" placeholder="USDT" /></label>
          <label>Timeframe<input required name="timeframe" placeholder="1h" /></label>
          {[["Calendar", "24×7"], ["Timestamp convention", "Bar open (UTC)"],
            ["Price basis", "Raw spot"], ["Volume unit", "Base quantity"]].map(([label, value]) =>
            <div key={label} className="fixed-label">{label}<span className="fixed">{value}</span></div>)}
        </div>
        <fieldset><legend>Gap policy</legend>
          <label><input type="radio" name="gap" value="reject" defaultChecked /> Reject gaps</label>
          <label><input type="radio" name="gap" value="allow" /> Allow gaps</label>
        </fieldset></>}
        <Notice error={error} />
        {busy && <Pending>Uploading and validating candles…</Pending>}
        <div className="actions form-actions">
          <button className="button" type="button" onClick={cancel} disabled={busy}>Cancel</button>
          <button className="button primary" disabled={busy}>Import dataset</button>
        </div>
      </form>
      <aside className="inspector">
        <h2>Gap policy</h2>
        <p>Choose a metadata file for exchange sessions or enter the fields for continuous candles.</p>
        <p>If you allow gaps, fills use the next observed open and rolling windows count observed candles.</p>
        <p>Sharpe is unavailable for gapped windows.</p>
      </aside>
    </div>
  </>;
}
