import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { TeamsLive } from "@/live/CatalogLive";

export const Route = createFileRoute("/admin/teams")({
  head: () => ({
    meta: [
      { title: "Teams — Football Intelligence" },
      {
        name: "description",
        content: "Canonical team entities, provider mappings and rating history.",
      },
      { property: "og:title", content: "Teams — Football Intelligence" },
      {
        property: "og:description",
        content: "Canonical team entities, provider mappings and rating history.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  return DATA_MODE === "mock" ? <Page /> : <TeamsLive />;
}

function Page() {
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Football" }, { label: "Teams" }]}
      title="Teams"
      description="Canonical team entities, provider mappings and rating history."
      purpose="Teams holds the canonical entity layer: one identity per club, mapped to every provider alias. Unresolved aliases are a data-quality defect, not a display issue, so this module surfaces mapping gaps alongside ratings and rolling form."
      sections={[
        {
          title: "Entity registry",
          description: "Canonical teams with provider identifiers and aliases.",
          state: "in-progress",
        },
        {
          title: "Mapping gaps",
          description: "Unknown or ambiguous provider entities awaiting resolution.",
          state: "in-progress",
        },
        {
          title: "Rating history",
          description: "Elo and strength parameters over time per team.",
          state: "planned",
        },
        {
          title: "Team profile",
          description: "Rolling form, goal process parameters and schedule strength.",
          state: "planned",
        },
      ]}
      dataNeeds={[
        "GET /teams",
        "GET /teams/:id",
        "GET /teams/:id/ratings",
        "GET /teams/mapping-gaps",
      ]}
    />
  );
}
