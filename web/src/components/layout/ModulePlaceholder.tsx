import { PageHeader } from "./PageHeader";
import { Panel, WarningBanner } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";

export interface PlaceholderSection {
  title: string;
  description: string;
  state?: "planned" | "in-progress" | "blocked";
}

const stateTone = {
  planned: "neutral",
  "in-progress": "brand",
  blocked: "warning",
} as const;

export function ModulePlaceholder({
  title,
  description,
  purpose,
  sections,
  dataNeeds,
  breadcrumb,
}: {
  title: string;
  description: string;
  purpose: string;
  sections: PlaceholderSection[];
  dataNeeds: string[];
  breadcrumb?: Array<{ label: string }>;
}) {
  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumb={breadcrumb}
        title={title}
        description={description}
        actions={<StatusBadge tone="warning">Module scaffold</StatusBadge>}
      />

      <WarningBanner>
        This module is scaffolded, not implemented. Nothing here is backed by validated output yet —
        the layout describes what the module will contain once the engine emits it.
      </WarningBanner>

      <div className="grid gap-5 lg:grid-cols-3">
        <Panel title="What this module does" className="lg:col-span-2">
          <p className="text-sm leading-relaxed text-muted-foreground">{purpose}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {sections.map((s) => (
              <div key={s.title} className="rounded-md border border-border bg-elevated/40 p-3">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-title">{s.title}</h3>
                  <StatusBadge tone={stateTone[s.state ?? "planned"]}>
                    {s.state ?? "planned"}
                  </StatusBadge>
                </div>
                <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
                  {s.description}
                </p>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Data this module requires" subtitle="Contracts expected from the backend">
          <ul className="space-y-2">
            {dataNeeds.map((d) => (
              <li key={d} className="flex items-start gap-2 text-xs text-muted-foreground">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" />
                <span className="numeric">{d}</span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
