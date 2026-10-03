import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { AnalyticsLive } from "@/live/AnalyticsLive";

export const Route = createFileRoute("/admin/analytics")({
  head: () => ({
    meta: [
      { title: "Analytics — Football Intelligence" },
      {
        name: "description",
        content: "Exploratory analysis across competitions, markets and time windows.",
      },
      { property: "og:title", content: "Analytics — Football Intelligence" },
      {
        property: "og:description",
        content: "Exploratory analysis across competitions, markets and time windows.",
      },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <AnalyticsLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Intelligence" }, { label: "Analytics" }]}
      title="Analytics"
      description="Exploratory analysis across competitions, markets and time windows."
      purpose="Analytics is the exploratory surface on top of the feature store: distribution of model-market disagreement, behaviour by competition and market, temporal drift and cohort comparisons. It is a research tool, not a reporting layer for results."
      sections={[
        {
          title: "Disagreement analysis",
          description: "Where the model and the market diverge most, and whether that persists.",
          state: "planned",
        },
        {
          title: "Segment explorer",
          description: "Slice by competition, market, price band and schedule context.",
          state: "planned",
        },
        {
          title: "Temporal drift",
          description: "Feature and probability stability across seasons and windows.",
          state: "planned",
        },
        {
          title: "Cohort comparison",
          description: "Compare model versions on identical fixture sets.",
          state: "planned",
        },
      ]}
      dataNeeds={["GET /analytics/disagreement", "GET /analytics/segments", "GET /analytics/drift"]}
    />
  );
}
