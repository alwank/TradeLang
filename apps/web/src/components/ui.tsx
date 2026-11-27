"use client";

import type { ReactNode } from "react";
import { ApiError } from "@/lib/api";

export function Notice({ error }: { error: unknown }) {
  if (!error) return null;
  const message = error instanceof Error ? error.message : String(error);
  const diagnostics = error instanceof ApiError ? error.diagnostics : [];
  return (
    <div className="notice error" role="alert">
      <strong>{message}</strong>
      {diagnostics.length > 0 && <ul>{diagnostics.map((item, i) => (
        <li key={i}>{item.data_row == null ? "" : `Row ${item.data_row} · `}{item.message}
          {item.suggestion && <span> {item.suggestion}</span>}
        </li>
      ))}</ul>}
    </div>
  );
}

export function Details({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="details">
      {rows.map(([label, value]) => (
        <div key={label}><dt>{label}</dt><dd>{value ?? "—"}</dd></div>
      ))}
    </dl>
  );
}

export function Pending({ children = "Loading…" }: { children?: ReactNode }) {
  return <p className="muted" role="status">{children}</p>;
}
