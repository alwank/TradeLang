import { DatasetLibrary } from "@/components/dataset-library";

export default async function DatasetsPage({
  searchParams,
}: { searchParams: Promise<{ strategy?: string }> }) {
  const { strategy } = await searchParams;
  return <DatasetLibrary strategyId={typeof strategy === "string" ? strategy : undefined} />;
}
