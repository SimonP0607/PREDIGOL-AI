import { createFileRoute } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { DATA_MODE } from "@/lib/api/mode";
import { RefereeLive } from "@/live/RefereesLive";

export const Route = createFileRoute("/admin/referees/$refereeId")({
  head: () => ({
    meta: [
      { title: "Referee · PrediGol Admin" },
      {
        name: "description",
        content:
          "A referee: his spellings, his matches, the doubts about him and the decisions taken.",
      },
    ],
  }),
  component: Page,
});

function Page() {
  const { refereeId } = Route.useParams();
  if (DATA_MODE !== "mock") return <RefereeLive refereeId={refereeId} />;
  return <PageHeader title="Referee" description="Referee identity is read from the API only." />;
}
