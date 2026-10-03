import { PageTitle } from "@/product/shared/States";

export function MatchPage({ fixtureId }: { fixtureId: string }) {
  return <PageTitle title={`#${fixtureId}`} />;
}
