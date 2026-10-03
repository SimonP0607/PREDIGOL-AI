import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { PlayersLive } from "@/live/PlayersLive";

const DESCRIPTION = "Players from line-ups and match statistics: search, squads and profiles.";

export const Route = createFileRoute("/admin/players/")({
  head: () => ({
    meta: [
      { title: "Players — Football Intelligence" },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: "Players — Football Intelligence" },
      { property: "og:description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <PlayersLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Football" }, { label: "Players" }]}
      title="Players"
      description={DESCRIPTION}
      purpose="Player data is read from the API only."
      sections={[{ title: "Player search", description: "From GET /players.", state: "blocked" }]}
      dataNeeds={["GET /players", "GET /players/:id"]}
    />
  );
}
