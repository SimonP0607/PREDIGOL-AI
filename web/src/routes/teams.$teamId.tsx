import { createFileRoute } from "@tanstack/react-router";
import { TeamPage } from "@/product/teams/TeamPage";
import { parseTab, type ProfileTab } from "@/product/teams/model";
import { titled } from "@/lib/i18n/head";

/** The profile of a club (plan maestro unificado, UX-154; maqueta 11): shown only while FBI_PROFILES is on. */
export const Route = createFileRoute("/teams/$teamId")({
  head: titled("profiles.clubTitle"),
  validateSearch: (s: Record<string, unknown>): { tab?: ProfileTab } => {
    const tab = parseTab(s["tab"]);
    return tab === "summary" ? {} : { tab };
  },
  component: Team,
});

function Team() {
  const { teamId } = Route.useParams();
  return <TeamPage teamId={teamId} />;
}
