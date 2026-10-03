import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { SettingsLive } from "@/live/ResearchLive";

export const Route = createFileRoute("/admin/settings")({
  head: () => ({
    meta: [
      { title: "Settings · PrediGol Admin" },
      {
        name: "description",
        content: "Workspace, thresholds, provider configuration and versioning preferences.",
      },
      { property: "og:title", content: "Settings · PrediGol Admin" },
      {
        property: "og:description",
        content: "Workspace, thresholds, provider configuration and versioning preferences.",
      },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <SettingsLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "System" }, { label: "Settings" }]}
      title="Settings"
      description="Workspace, thresholds, provider configuration and versioning preferences."
      purpose="Settings controls the operational parameters of the research workspace: decision thresholds, snapshot cadence, tracked bookmakers, competition scope and which model versions are allowed to emit candidates."
      sections={[
        {
          title: "Decision thresholds",
          description: "Minimum edge, minimum sample and reliability gates for candidates.",
          state: "planned",
        },
        {
          title: "Provider configuration",
          description: "API quota, capture cadence and retry policy.",
          state: "planned",
        },
        {
          title: "Tracked markets",
          description: "Which markets and bookmakers form the consensus.",
          state: "planned",
        },
        {
          title: "Model release",
          description: "Which versions may run in shadow and which may publish.",
          state: "planned",
        },
      ]}
      dataNeeds={["GET /settings", "PATCH /settings", "GET /settings/thresholds"]}
    />
  );
}
