import { RunRevision } from "@/components/run-revision";

export default async function RevisionPage({
  params,
}: { params: Promise<{ id: string; revision: string }> }) {
  const { id, revision } = await params;
  return <RunRevision id={id} revision={Number(revision)} />;
}
