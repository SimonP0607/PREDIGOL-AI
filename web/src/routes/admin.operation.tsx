import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { OperationLive } from "@/live/OperationLive";

const DESCRIPTION =
  "The day of PrediGol Intelligence and of the AI: what was analysed and decided, the dossier of each match, the AI's work, what it costs and what ran.";

export const Route = createFileRoute("/admin/operation")({
  head: () => ({
    meta: [
      { title: "Operation · PrediGol Admin" },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: "Operation · PrediGol Admin" },
      { property: "og:description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <OperationLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Intelligence" }, { label: "Operation" }]}
      title="Operation"
      description={DESCRIPTION}
      purpose="Operation is read from the API only."
      sections={[
        {
          title: "The day, the decisions and the dossier of a match",
          description: "From GET /admin/intelligence/*.",
          state: "blocked",
        },
        {
          title: "The AI's work",
          description:
            "From GET /admin/ai/*: today, research, research by entity and topic, reviews, evidence and sources.",
          state: "blocked",
        },
        {
          title: "Costs and runs",
          description: "From GET /admin/ai/costs, GET /admin/intelligence/costs and /runs.",
          state: "blocked",
        },
      ]}
      dataNeeds={[
        "GET /admin/intelligence/day",
        "GET /admin/intelligence/decisions",
        "GET /admin/intelligence/matches",
        "GET /admin/intelligence/runs",
        "GET /admin/intelligence/costs",
        "GET /admin/ai/overview",
        "GET /admin/ai/today",
        "GET /admin/ai/research",
        "GET /admin/ai/research/entities",
        "GET /admin/ai/reviews",
        "GET /admin/ai/evidence",
        "GET /admin/ai/sources",
        "GET /admin/ai/costs",
      ]}
    />
  );
}
