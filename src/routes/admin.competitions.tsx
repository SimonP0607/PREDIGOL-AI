import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { CompetitionsLive } from "@/live/CatalogLive";

export const Route = createFileRoute("/admin/competitions")({
  head: () => ({
    meta: [
      { title: "Competitions — Football Intelligence" },
      {
        name: "description",
        content: "Coverage, calendar completeness and data readiness per competition.",
      },
      { property: "og:title", content: "Competitions — Football Intelligence" },
      {
        property: "og:description",
        content: "Coverage, calendar completeness and data readiness per competition.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  return DATA_MODE === "mock" ? <Page /> : <CompetitionsLive />;
}

function Page() {
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Football" }, { label: "Competitions" }]}
      title="Competitions"
      description="Coverage, calendar completeness and data readiness per competition."
      purpose="The competitions module tracks which leagues the system actually covers to a usable standard: fixtures ingested versus expected, odds availability, model readiness and the historical depth available for training."
      sections={[
        {
          title: "Coverage matrix",
          description: "Fixtures expected vs ingested vs priced, per competition and round.",
          state: "in-progress",
        },
        {
          title: "Historical depth",
          description: "Seasons available in the v2 store and their validation state.",
          state: "planned",
        },
        {
          title: "Model readiness",
          description: "Which models have sufficient sample for each competition.",
          state: "planned",
        },
        {
          title: "Calendar",
          description: "Upcoming rounds and ingestion schedule.",
          state: "planned",
        },
      ]}
      dataNeeds={["GET /competitions", "GET /competitions/:id", "GET /competitions/:id/coverage"]}
    />
  );
}
