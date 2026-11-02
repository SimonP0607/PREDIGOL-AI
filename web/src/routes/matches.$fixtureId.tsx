import { createFileRoute } from "@tanstack/react-router";
import { MatchPage } from "@/product/match/MatchPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/matches/$fixtureId")({
  head: titled("nav.matches"),
  component: MatchRoute,
});

function MatchRoute() {
  const { fixtureId } = Route.useParams();
  return <MatchPage fixtureId={fixtureId} />;
}
