import type { Strategy } from "./api";

export type Draft = { source: string; revision: number; hash: string };
const key = (id: string) => `tradelang.draft.v1.${id}`;

export function loadDraft(id: string): Draft | undefined {
  const draft = JSON.parse(sessionStorage.getItem(key(id)) ?? "null");
  if (draft && typeof draft.source === "string" && Number.isSafeInteger(draft.revision) &&
    typeof draft.hash === "string") return draft;
}

export function storeDraft(saved: Strategy, source: string) {
  if (source === saved.current_source) sessionStorage.removeItem(key(saved.id));
  else sessionStorage.setItem(key(saved.id), JSON.stringify({
    source, revision: saved.current_revision, hash: saved.source_hash,
  } satisfies Draft));
}
