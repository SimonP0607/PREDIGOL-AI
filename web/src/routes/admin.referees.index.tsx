import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { RefereesLive } from "@/live/RefereesLive";

const DESCRIPTION =
  "Referees as people: their spellings, the doubts the rules could not settle and the decisions taken.";

export const Route = createFileRoute("/admin/referees/")({
  head: () => ({
    meta: [
      { title: "Referees · PrediGol Admin" },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: "Referees · PrediGol Admin" },
      { property: "og:description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <RefereesLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Football" }, { label: "Referees" }]}
      title="Referees"
      description={DESCRIPTION}
      purpose="Referee identity is read from the API only."
      sections={[
        { title: "People and doubts", description: "From GET /admin/referees.", state: "blocked" },
      ]}
      dataNeeds={["GET /admin/referees", "GET /admin/referees/queue", "GET /admin/referees/:id"]}
    />
  );
}
