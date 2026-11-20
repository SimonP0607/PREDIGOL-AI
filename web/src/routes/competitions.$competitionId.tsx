import { createFileRoute } from "@tanstack/react-router";
import { CompetitionPage } from "@/product/competitions/CompetitionPage";
import { titled } from "@/lib/i18n/head";

/** A competition's page (plan PM, PM-09-04; UX-178; lámina I07): shown only while FBI_COMPETITION_PAGE is on. */
export const Route = createFileRoute("/competitions/$competitionId")({
  head: titled("profiles.competitionTitle"),
  validateSearch: (s: Record<string, unknown>): { tab?: string } =>
    typeof s["tab"] === "string" ? { tab: s["tab"] } : {},
  component: Competition,
});

function Competition() {
  const { competitionId } = Route.useParams();
  return <CompetitionPage competitionId={competitionId} />;
}
