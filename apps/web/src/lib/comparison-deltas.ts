import type { components } from "./schema";

export type Comparison = components["schemas"]["Comparison"];
type Run = components["schemas"]["ComparisonRun"];
export type Metric = "total_return" | "final_equity" | "max_drawdown" | "closed_trades" |
  "cagr" | "sharpe" | "win_rate" | "profit_factor";
const rates = new Set<Metric>(["total_return", "max_drawdown", "cagr", "win_rate"]);

const fields = {
  market: "Market",
  currency: "Quote currency",
  timeframe_seconds: "Timeframe",
  calendar: "Calendar",
  semantics_version: "Semantics version",
};
const bounds = ["first_open", "last_close_at"];
const signed = new Intl.NumberFormat("en", { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "exceptZero" });
const signedCount = new Intl.NumberFormat("en", { maximumFractionDigits: 0, signDisplay: "exceptZero" });
const hasValue = (value: unknown) => (typeof value === "string" && value.trim() !== "") ||
  (typeof value === "number" && Number.isFinite(value));

export function metricValue(run: Run, key: Metric) {
  return key === "final_equity" ? run.final_equity : run.metrics[key];
}

export function pairDifference(comparison: Comparison, baselineIndex: number, candidateIndex: number) {
  const baseline = comparison.runs[baselineIndex].configuration;
  const candidate = comparison.runs[candidateIndex].configuration;
  if (bounds.some((field) => !hasValue(baseline[field]) || !hasValue(candidate[field]))) {
    return "Full-run bounds are unavailable.";
  }
  if (bounds.some((field) => baseline[field] !== candidate[field])) return "Full-run windows differ.";
  const incompatible = new Map(comparison.differences.filter(({ severity }) => severity === "incompatible")
    .map(({ field, values }) => [field, values]));
  for (const [field, label] of Object.entries(fields)) {
    const values = incompatible.get(field);
    const before = values ? values[baselineIndex] : baseline[field];
    const after = values ? values[candidateIndex] : candidate[field];
    if (!hasValue(before) || !hasValue(after)) return `${label} is unavailable.`;
    if (before !== after) return `${label} differs.`;
  }
}

export function metricDelta(baseline: Run, candidate: Run, key: Metric, pairReason?: string) {
  if (pairReason) return { reason: pairReason };
  const before = metricValue(baseline, key);
  const after = metricValue(candidate, key);
  if (typeof before !== "number" || typeof after !== "number" ||
    !Number.isFinite(before) || !Number.isFinite(after)) return { reason: "Metric is unavailable in one or both runs." };
  if (key === "final_equity") {
    if (!hasValue(baseline.configuration.capital) || !hasValue(candidate.configuration.capital)) {
      return { reason: "Starting capital is unavailable." };
    }
    if (baseline.configuration.capital !== candidate.configuration.capital) return { reason: "Starting capital differs." };
  }
  const change = (after - before) * (rates.has(key) ? 100 : 1);
  if (!Number.isFinite(change)) return { reason: "Metric difference is unavailable." };
  const unit = key === "final_equity" ? ` ${baseline.configuration.currency}` : rates.has(key) ? " pp" : "";
  return { value: (key === "closed_trades" ? signedCount : signed).format(change).replace("-", "−") + unit };
}
