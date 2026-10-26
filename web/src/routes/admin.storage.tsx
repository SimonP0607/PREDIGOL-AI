import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { StorageLive } from "@/live/StorageLive";

const DESCRIPTION = "Disk, database, RAW, Docker, copies, cleanup and retention policy. Read-only.";

export const Route = createFileRoute("/admin/storage")({
  head: () => ({
    meta: [
      { title: "Storage / Admin · PrediGol Admin" },
      { name: "description", content: DESCRIPTION },
    ],
  }),
  component: Page,
});

function Page() {
  if (DATA_MODE !== "mock") return <StorageLive />;
  return (
    <ModulePlaceholder
      breadcrumb={[{ label: "System" }, { label: "Storage" }]}
      title="Storage"
      description={DESCRIPTION}
      purpose="The storage view reads the server's own report and has no demo version."
      sections={[{ title: "Storage", description: "From GET /admin/storage.", state: "blocked" }]}
      dataNeeds={["GET /admin/storage"]}
    />
  );
}
