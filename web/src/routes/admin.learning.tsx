import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { LearningLive } from "@/live/LearningLive";

const DESCRIPTION =
  "What PrediGol learns: the close of each day, what was learned and proposed, post-mortems, memory, experiments, calibration, markets and the AI against the model.";

export const Route = createFileRoute("/admin/learning")({
  head: () => ({
    meta: [
      { title: "Learning · PrediGol Admin" },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: "Learning · PrediGol Admin" },
      { property: "og:description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <LearningLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Intelligence" }, { label: "Learning" }]}
      title="Learning"
      description={DESCRIPTION}
      purpose="Learning is read from the API only."
      sections={[
        {
          title: "The close of the day, what was learned and the post-mortems",
          description:
            "From GET /admin/ai/report, GET /admin/evolution/dashboard and /admin/ai/postmortems.",
          state: "blocked",
        },
        {
          title: "Memory",
          description: "From GET /admin/intelligence/memory and GET /admin/ai/*.",
          state: "blocked",
        },
        {
          title: "Experiments and the model code",
          description: "From GET /admin/evolution and GET /admin/evolution/code-promotions.",
          state: "blocked",
        },
        {
          title: "Calibration, markets and the AI against the model",
          description: "From GET /admin/intelligence/* and GET /admin/ai/comparison.",
          state: "blocked",
        },
      ]}
      dataNeeds={[
        "GET /admin/ai/report",
        "GET /admin/ai/postmortems",
        "GET /admin/ai/match-memory",
        "GET /admin/ai/memory",
        "GET /admin/ai/shadow",
        "GET /admin/ai/comparison",
        "GET /admin/evolution",
        "GET /admin/evolution/dashboard",
        "GET /admin/evolution/code-promotions",
        "GET /admin/intelligence/memory",
        "GET /admin/intelligence/calibration",
        "GET /admin/intelligence/markets",
      ]}
    />
  );
}
