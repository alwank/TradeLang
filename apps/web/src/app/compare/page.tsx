import { CompareRuns } from "@/components/compare-runs";

export default async function ComparePage({ searchParams }: { searchParams: Promise<{ ids?: string }> }) {
  const { ids } = await searchParams;
  return <CompareRuns ids={typeof ids === "string" ? ids : ""} />;
}
