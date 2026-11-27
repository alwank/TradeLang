export type Attempt = { key: string; at: number };
const MAX_AGE = 24 * 60 * 60 * 1000;
const MAX_ATTEMPTS = 24;
const storageKey = (strategyId: string) => `tradelang.submissions.v1.${strategyId}`;

export function pruneAttempts(attempts: Map<string, Attempt>, now = Date.now()) {
  for (const [identity, attempt] of attempts) {
    if (now - attempt.at >= MAX_AGE || attempt.at > now) attempts.delete(identity);
  }
  for (const identity of attempts.keys()) {
    if (attempts.size <= MAX_ATTEMPTS) break;
    attempts.delete(identity);
  }
}

export function loadAttempts(strategyId: string) {
  const attempts = new Map<string, Attempt>();
  try {
    const stored: unknown = JSON.parse(sessionStorage.getItem(storageKey(strategyId)) ?? "null");
    if (Array.isArray(stored)) {
      for (const row of stored.slice(-MAX_ATTEMPTS)) {
        if (Array.isArray(row) && typeof row[0] === "string" && typeof row[1]?.key === "string" &&
          Number.isFinite(row[1]?.at)) attempts.set(row[0], row[1]);
      }
      pruneAttempts(attempts);
    }
  } catch {}
  return attempts;
}

export function storeAttempts(strategyId: string, attempts: Map<string, Attempt>) {
  pruneAttempts(attempts);
  try {
    const key = storageKey(strategyId);
    if (attempts.size) sessionStorage.setItem(key, JSON.stringify([...attempts]));
    else sessionStorage.removeItem(key);
  } catch {}
}
