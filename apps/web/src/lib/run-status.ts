"use client";

import { useCallback, useSyncExternalStore } from "react";
import { api, read } from "./api";
import type { components } from "./schema";

export type Run = components["schemas"]["RunView"];
type Snapshot = { run?: Run; error?: unknown; cancelling?: boolean };
type Tracker = {
  snapshot: Snapshot;
  listeners: Set<() => void>;
  read?: AbortController;
  timer?: ReturnType<typeof setTimeout>;
  delay: number;
};

const empty: Snapshot = {};
const trackers = new Map<string, Tracker>();
const serverSnapshot = () => empty;

export function isActive(run: Run) {
  return run.status === "queued" || run.status === "running";
}

export function runStatus(run: Run) {
  if (isActive(run) && run.cancel_requested) return "Cancelling";
  if (run.status === "failed" && run.error?.code === "E_INTERRUPTED") return "Interrupted";
  return run.status.charAt(0).toUpperCase() + run.status.slice(1);
}

function report(tracker: Tracker, snapshot: Snapshot) {
  tracker.snapshot = snapshot;
  tracker.listeners.forEach((listener) => listener());
}

function schedule(id: string, tracker: Tracker) {
  tracker.timer = setTimeout(() => void poll(id, tracker), tracker.delay);
  tracker.delay = Math.min(tracker.delay + 1000, 5000);
}

function stopRead(tracker: Tracker) {
  clearTimeout(tracker.timer);
  tracker.read?.abort();
  tracker.read = undefined;
}

async function poll(id: string, tracker: Tracker) {
  stopRead(tracker);
  const request = new AbortController();
  tracker.read = request;
  try {
    const run = read(await api.GET("/api/v1/backtests/{ident}", {
      params: { path: { ident: id } }, signal: request.signal,
    }));
    if (request.signal.aborted) return;
    report(tracker, { run });
    if (isActive(run)) schedule(id, tracker);
  } catch (error) {
    if (!request.signal.aborted) report(tracker, { run: tracker.snapshot.run, error });
  } finally {
    if (tracker.read === request) tracker.read = undefined;
  }
}

function subscribe(id: string, listener: () => void, seed?: Run) {
  let tracker = trackers.get(id);
  if (!tracker) {
    tracker = { snapshot: seed ? { run: seed } : empty, listeners: new Set(), delay: 1000 };
    trackers.set(id, tracker);
    if (!seed) void poll(id, tracker);
    else if (isActive(seed)) schedule(id, tracker);
  }
  const observed = tracker;
  observed.listeners.add(listener);
  return () => {
    observed.listeners.delete(listener);
    if (!observed.listeners.size) {
      stopRead(observed);
      trackers.delete(id);
    }
  };
}

export function useRunStatus(id: string | undefined, seed?: Run) {
  const watch = useCallback((listener: () => void) => id ? subscribe(id, listener, seed) : () => {}, [id, seed]);
  const snapshot = useSyncExternalStore(watch, () => (id ? trackers.get(id)?.snapshot : undefined) ?? empty, serverSnapshot);

  function retry() {
    if (!id) return;
    const tracker = trackers.get(id);
    if (!tracker || tracker.snapshot.cancelling) return;
    tracker.delay = 1000;
    void poll(id, tracker);
  }

  async function cancel() {
    if (!id) return;
    const tracker = trackers.get(id);
    const run = tracker?.snapshot.run;
    if (!tracker || !run || !isActive(run) || run.cancel_requested || tracker.snapshot.cancelling) return;
    stopRead(tracker);
    report(tracker, { run, cancelling: true });
    try {
      const updated = read(await api.POST("/api/v1/backtests/{ident}/cancel", {
        params: { path: { ident: id } }, body: {},
      }));
      if (trackers.get(id) !== tracker) return;
      report(tracker, { run: updated });
      tracker.delay = 1000;
      if (isActive(updated)) schedule(id, tracker);
    } catch (error) {
      if (trackers.get(id) === tracker) report(tracker, { run, error });
    }
  }

  return { ...snapshot, run: snapshot.run ?? seed, retry, cancel };
}
