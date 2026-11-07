import { createFileRoute } from "@tanstack/react-router";
import { MatchPage } from "@/product/match/MatchPage";
import { titled } from "@/lib/i18n/head";

export const Route = createFileRoute("/matches/$fixtureId")({
  // The section (`?s=noticias`) and the pick a link comes from (`?pick=45`, «Más sobre este pick»): both read from the
  // address by the match itself, named here so a link can write them.
  validateSearch: (
    s: Record<string, unknown>,
  ): { s?: string | undefined; pick?: number | undefined } => {
    const pick = Number(s["pick"]);
    return {
      s: typeof s["s"] === "string" ? s["s"] : undefined,
      pick: Number.isInteger(pick) && pick > 0 ? pick : undefined,
    };
  },
  head: titled("nav.matches"),
  component: MatchRoute,
});

function MatchRoute() {
  const { fixtureId } = Route.useParams();
  return <MatchPage fixtureId={fixtureId} />;
}
