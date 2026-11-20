import { createFileRoute } from "@tanstack/react-router";
import { ModulePlaceholder } from "@/components/layout/ModulePlaceholder";
import { DATA_MODE } from "@/lib/api/mode";
import { CompetitionsLive } from "@/live/CatalogLive";
import { SegmentedTabs } from "@/components/system/Filters";
import { AvailabilityConsole } from "@/admin/AvailabilityConsole";
import { t } from "@/product/shared/availabilityText";
import { useAvailabilityOn } from "@/lib/auth/AuthProvider";
import { useUrlTab } from "@/lib/useUrlTab";

export const Route = createFileRoute("/admin/competitions")({
  head: () => ({
    meta: [
      { title: "Competitions · PrediGol Admin" },
      {
        name: "description",
        content: "Coverage, calendar completeness and data readiness per competition.",
      },
      { property: "og:title", content: "Competitions · PrediGol Admin" },
      {
        property: "og:description",
        content: "Coverage, calendar completeness and data readiness per competition.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  if (DATA_MODE === "mock") return <Page />;
  return <LiveTabs />;
}

const TABS = ["catalog", "availability"] as const;

/**
 * The catalogue as it was and, with C-16 on (FBI_AVAILABILITY, plan PM, PM-02-08), the tab of the availability matrix (I11).
 * With the switch off the page is exactly the catalogue: no tab strip.
 */
function LiveTabs() {
  const on = useAvailabilityOn();
  const [tab, setTab] = useUrlTab(TABS, "catalog");
  if (!on) return <CompetitionsLive />;
  return (
    <div className="space-y-4">
      <SegmentedTabs
        label={t("availability.console.tabsLabel")}
        tabs={TABS}
        value={tab}
        onChange={setTab}
        format={(v) =>
          v === "catalog" ? t("availability.console.catalogTab") : t("availability.console.tab")
        }
        className="w-auto"
      />
      {tab === "availability" ? <AvailabilityConsole /> : <CompetitionsLive />}
    </div>
  );
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
