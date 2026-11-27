"use client";

import Link from "next/link";
import { useCallback, useRef } from "react";
import type { EditorView } from "@codemirror/view";
import { api, read } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { CodeEditor } from "./code-editor";
import { Notice, Pending } from "./ui";
import { Time } from "./shell";

export function RunRevision({ id, revision }: { id: string; revision: number }) {
  const snapshot = useResource(useCallback(async (signal) => read(await api.GET(
    "/api/v1/strategies/{ident}/revisions/{revision}",
    { params: { path: { ident: id, revision } }, signal },
  )), [id, revision]));
  const strategy = useResource(useCallback(async (signal) => {
    const response = await api.GET("/api/v1/strategies/{ident}", { params: { path: { ident: id } }, signal });
    return response.response.ok ? read(response) : undefined;
  }, [id]));
  const sourceName = /^\s*strategy\s+"([^"\n]+)"/m.exec(snapshot.data?.source ?? "")?.[1];
  const name = strategy.data?.name ?? sourceName;
  const editor = useRef<EditorView | null>(null);
  return <>
    <div className="page-heading bar">
      <div className="heading-copy">
        <h1>{name ? `${name} · Revision ${revision}` : `Strategy revision ${revision}`}</h1>
        <p className="muted">Saved <Time value={snapshot.data?.created_at} /> · Read-only</p>
      </div>
      <div className="actions">
        {snapshot.data && <details className="disclosure fingerprint"><summary>Source fingerprint</summary>
          <code>{snapshot.data.source_hash}</code>
        </details>}
        <Link className="button" href={strategy.data ? `/strategies/${id}` : "/strategies"}>
          {strategy.data ? "Open current strategy" : "Open Strategies"}
        </Link>
      </div>
    </div>
    <Notice error={snapshot.error} />
    {snapshot.error ? <button className="button" onClick={snapshot.reload}>Retry</button>
      : snapshot.data ? <section className="revision-source" aria-label="Saved strategy source">
        <CodeEditor key={snapshot.data.id} source={snapshot.data.source} diagnostics={[]} readOnly editor={editor} onEdit={() => {}} />
      </section> : <Pending />}
  </>;
}
