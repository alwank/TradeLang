import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export const api = createClient<paths>({
  fetch: async (request) => {
    try {
      return await fetch(request);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
      throw new ApiError(503, "The local API is unavailable. Check that TradeLang is running.");
    }
  },
});

export type Diagnostic = components["schemas"]["Diagnostic"];
export type Strategy = components["schemas"]["StrategyRecord"];
export type Dataset = components["schemas"]["DatasetSummary"];
export type DatasetDetail = components["schemas"]["DatasetRecord"];
export type Validation = components["schemas"]["CompilationResponse"];
export type DraftCheck = components["schemas"]["DraftCheckResponse"];
export type RunPreset = components["schemas"]["RunPreset"];
export type RunSettings = components["schemas"]["RunSettings"];
export type RunConfiguration = components["schemas"]["RunConfiguration"];
export type Explanation = components["schemas"]["ExplainResponse"];
export type Health = components["schemas"]["Health"];

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public diagnostics: Diagnostic[] = [],
    public code?: string,
  ) {
    super(message);
  }
}

function apiError(response: Response, value: unknown) {
  if (value && typeof value === "object" && "error" in value) {
    const problem = (value as components["schemas"]["ErrorEnvelope"]).error;
    if (typeof problem?.message === "string") {
      const retryAfter = response.headers.get("Retry-After");
      const message = retryAfter ? `${problem.message}. Retry in ${retryAfter} seconds.` : problem.message;
      return new ApiError(response.status, message, problem.diagnostics, problem.code);
    }
  }
  return new ApiError(response.status, response.status >= 500
    ? "The local API is unavailable. Check that TradeLang is running."
    : `TradeLang could not complete the request (HTTP ${response.status}).`);
}

export function read<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (!result.response.ok || result.data === undefined) {
    throw apiError(result.response, result.error);
  }
  return result.data;
}

export function accepted(result: { error?: unknown; response: Response }) {
  if (!result.response.ok) throw apiError(result.response, result.error);
}

export async function upload(form: FormData): Promise<components["schemas"]["Imported"]> {
  let response: Response;
  try {
    response = await fetch("/api/v1/datasets/import", { method: "POST", body: form });
  } catch {
    throw new ApiError(503, "The local API is unavailable. Check that TradeLang is running.");
  }
  const body = await response.json().catch(() => undefined);
  if (!response.ok) throw apiError(response, body);
  return body;
}
