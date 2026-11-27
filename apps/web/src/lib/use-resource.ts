"use client";

import { useEffect, useState } from "react";

export function useResource<T>(load: (signal: AbortSignal) => Promise<T>) {
  const [result, setResult] = useState<{ load: typeof load; attempt: number; data?: T; error?: unknown }>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => { if (!controller.signal.aborted) setResult({ load, attempt, data }); },
      (error) => { if (!controller.signal.aborted) setResult({ load, attempt, error }); },
    );
    return () => controller.abort();
  }, [load, attempt]);

  const current = result?.load === load && result.attempt === attempt ? result : undefined;
  return { data: current?.data, error: current?.error, reload: () => setAttempt((value) => value + 1) };
}
