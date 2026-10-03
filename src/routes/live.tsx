import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { LiveBoardLive } from "@/live/LiveBoardLive";

const DESCRIPTION =
  "Tracked matches in play: score, minute, events, statistics and in-play prices.";

export const Route = createFileRoute("/live")({
  head: () => ({
    meta: [
      { title: "Live — Football Intelligence" },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: "Live — Football Intelligence" },
      { property: "og:description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <LiveBoardLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Operations" }, { label: "Live" }]}
      title="Live"
      description={DESCRIPTION}
      purpose="Live Intelligence needs the running API: in-play data cannot be demonstrated with demo numbers without looking real."
      sections={[{ title: "Matches in play", description: "From GET /live.", state: "blocked" }]}
      dataNeeds={["GET /live"]}
    />
  );
}
