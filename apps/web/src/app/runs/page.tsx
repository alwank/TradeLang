import { RunHistory } from "@/components/run-history";

export default async function RunsPage({ searchParams }: { searchParams: Promise<{ ids?: string; baseline?: string }> }) {
  const { ids, baseline } = await searchParams;
  const selection = typeof ids === "string" ? [...new Set(ids.toLowerCase().split(","))].slice(0, 4) : [];
  const pin = typeof baseline === "string" ? baseline.toLowerCase() : undefined;
  return <RunHistory key={`${selection.join(",")};${pin ?? ""}`} baseline={pin} initialSelection={selection} />;
}
