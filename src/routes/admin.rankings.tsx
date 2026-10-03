import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { RankingsLive } from "@/live/RankingsLive";

export const Route = createFileRoute("/admin/rankings")({
  head: () => ({
    meta: [
      { title: "Rankings · PrediGol Admin" },
      {
        name: "description",
        content: "Model-derived strength rankings, separate from league tables.",
      },
      { property: "og:title", content: "Rankings · PrediGol Admin" },
      {
        property: "og:description",
        content: "Model-derived strength rankings, separate from league tables.",
      },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <RankingsLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Football" }, { label: "Rankings" }]}
      title="Rankings"
      description="Model-derived strength rankings, separate from league tables."
      purpose="Rankings expose the model's own view of team strength — rating, attack and defense parameters — explicitly distinguished from league standings. A ranking is a model output and carries the same version and cutoff metadata as any prediction."
      sections={[
        {
          title: "Strength table",
          description: "Ranked ratings with confidence intervals where available.",
          state: "planned",
        },
        {
          title: "Parameter breakdown",
          description: "Attack, defense and home effect per team.",
          state: "planned",
        },
        {
          title: "Movement",
          description: "Rating change across the last windows.",
          state: "planned",
        },
        {
          title: "Cross-league scaling",
          description: "How ratings compare between competitions.",
          state: "blocked",
        },
      ]}
      dataNeeds={["GET /rankings", "GET /rankings/:competition_id"]}
    />
  );
}
