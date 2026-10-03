import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { AdminLive } from "@/live/AdminLive";

const DESCRIPTION =
  "Private operations view: worker, quota, migration, captures, errors, quality, backups, versions.";

export const Route = createFileRoute("/admin/system")({
  head: () => ({
    meta: [
      { title: "System / Admin — Football Intelligence" },
      { name: "description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <AdminLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "System" }, { label: "System / Admin" }]}
      title="System / Admin"
      description={DESCRIPTION}
      purpose="The admin view reads the running system and has no demo version."
      sections={[
        { title: "Operations", description: "From GET /admin/overview.", state: "blocked" },
      ]}
      dataNeeds={["GET /admin/overview"]}
    />
  );
}
