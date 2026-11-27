export const integer = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const decimals = new Intl.NumberFormat("en", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const precise = new Intl.NumberFormat("en", { maximumFractionDigits: 8 });
const percent = new Intl.NumberFormat("en", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function money(value: number | null | undefined, currency?: string) {
  if (value == null) return "Unavailable";
  return `${decimals.format(value)}${currency ? ` ${currency}` : ""}`;
}

export function ratio(value: number | null | undefined) {
  return value == null ? "Unavailable" : percent.format(value === 0 ? 0 : value);
}

export function numeric(value: number | null | undefined) {
  return value == null ? "Unavailable" : precise.format(value === 0 ? 0 : value);
}

export function memory(value: number) {
  return value >= 1024 ** 2 ? `${decimals.format(value / 1024 ** 2)} MiB`
    : value >= 1024 ? `${decimals.format(value / 1024)} KiB`
    : `${integer.format(value)} bytes`;
}

export function title(label: string) {
  return label.replaceAll("_", " ").replace(/^./, (initial) => initial.toUpperCase());
}

export function scalar(value: unknown) {
  if (value == null) return "—";
  if (typeof value === "number") return numeric(value);
  return String(value);
}

export function presetLabel(value: unknown) {
  if (typeof value !== "object" || value === null || !("name" in value) || !("revision" in value)) return;
  if (typeof value.name === "string" && typeof value.revision === "number") {
    return `${value.name} · revision ${value.revision}`;
  }
}

export function feedLabels(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((feed) =>
    `${feed.name} · ${feed.timeframe_seconds}s · max age ${feed.max_age_seconds}s · ${feed.policy} · ${feed.dataset_hash}`);
}
