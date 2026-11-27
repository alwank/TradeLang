import { StrategyEditor } from "@/components/strategy-editor";

export default async function StrategyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StrategyEditor key={id} id={id} />;
}
