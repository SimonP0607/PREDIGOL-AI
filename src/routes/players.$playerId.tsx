import { createFileRoute } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { DATA_MODE } from "@/lib/api/mode";
import { PlayerLive } from "@/live/PlayersLive";

export const Route = createFileRoute("/players/$playerId")({
  head: () => ({
    meta: [
      { title: "Player — Football Intelligence" },
      { name: "description", content: "A player's profile, seasons, recent matches and absences." },
    ],
  }),
  component: Page,
});

function Page() {
  const { playerId } = Route.useParams();
  if (DATA_MODE !== "mock") return <PlayerLive playerId={playerId} />;
  return <PageHeader title="Player" description="Player profiles are read from the API only." />;
}
