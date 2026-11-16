import { createFileRoute } from "@tanstack/react-router";
import { TeamPage } from "@/product/teams/TeamPage";
import { parseTab, type ProfileTab } from "@/product/teams/model";
import { titled } from "@/lib/i18n/head";

/** The profile of a national team (plan maestro unificado, UX-155; maqueta 12): shown only while FBI_PROFILES is on. */
export const Route = createFileRoute("/nations/$teamId")({
  head: titled("profiles.nationTitle"),
  validateSearch: (s: Record<string, unknown>): { tab?: ProfileTab } => {
    const tab = parseTab(s["tab"]);
    return tab === "summary" ? {} : { tab };
  },
  component: Nation,
});

function Nation() {
  const { teamId } = Route.useParams();
  return <TeamPage teamId={teamId} nation />;
}
