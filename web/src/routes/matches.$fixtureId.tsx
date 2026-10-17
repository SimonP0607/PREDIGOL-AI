import { createFileRoute } from "@tanstack/react-router";
import { MatchPage } from "@/product/match/MatchPage";

export const Route = createFileRoute("/matches/$fixtureId")({
  head: () => ({ meta: [{ title: "PrediGol" }] }),
  component: MatchRoute,
});

function MatchRoute() {
  const { fixtureId } = Route.useParams();
  return <MatchPage fixtureId={fixtureId} />;
}
