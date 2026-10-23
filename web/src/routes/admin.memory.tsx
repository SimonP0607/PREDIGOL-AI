import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { MemoryLive } from "@/live/MemoryLive";

const DESCRIPTION =
  "What PrediGol has learned: entities over time with confidence and evidence, matches, post-mortems, learning notes and research findings.";

export const Route = createFileRoute("/admin/memory")({
  head: () => ({
    meta: [
      { title: "Memory · PrediGol Admin" },
      { name: "description", content: DESCRIPTION },
      { property: "og:title", content: "Memory · PrediGol Admin" },
      { property: "og:description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <MemoryLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "Intelligence" }, { label: "Memory" }]}
      title="Memory"
      description={DESCRIPTION}
      purpose="Memory is read from the API only."
      sections={[
        {
          title: "Entities, matches, post-mortems and notes",
          description: "From GET /admin/intelligence/memory and GET /admin/ai/*.",
          state: "blocked",
        },
      ]}
      dataNeeds={[
        "GET /admin/intelligence/memory",
        "GET /admin/ai/match-memory",
        "GET /admin/ai/postmortems",
        "GET /admin/ai/memory",
        "GET /admin/evolution",
      ]}
    />
  );
}
