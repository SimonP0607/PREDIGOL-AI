import { useMemo, useState } from "react";
import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { EmptyState, MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { DataStateBadge, StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { FreshnessBadge } from "@/components/system/Freshness";
import { LineageChain, SeverityBadge } from "@/components/system/Timelines";
import { FilterBar, SegmentedTabs, SelectFilter } from "@/components/system/Filters";
import { queries } from "@/lib/api/resources";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { DataQualityLive } from "@/live/DataQualityLive";
import { dateTimeOf, pct } from "@/lib/format";

export const Route = createFileRoute("/admin/data-quality")({
  head: () => ({
    meta: [
      { title: "Data Quality — Football Intelligence" },
      {
        name: "description",
        content:
          "Ingestion completeness, odds coverage, stale captures, provider errors and entity mapping gaps.",
      },
      { property: "og:title", content: "Data Quality — Football Intelligence" },
      {
        property: "og:description",
        content: "Ingestion completeness and coverage monitoring for the football data pipeline.",
      },
    ],
  }),
  component: DataQualityRoute,
});

function DataQualityRoute() {
  if (DATA_MODE === "mock") {
    return (
      <DemoRegion>
        <DataQualityPage />
      </DemoRegion>
    );
  }
  return <DataQualityLive />;
}

const tabs = ["Overview", "Coverage", "Issues", "Lineage"] as const;
type Tab = (typeof tabs)[number];

function DataQualityPage() {
  const [tab, setTab] = useState<Tab>("Overview");
  const dq = useQuery(queries.dataQuality);
  const health = useQuery(queries.health);
  const coverage = useQuery(queries.coverage);
  const issues = useQuery(queries.issues);
  const lineage = useQuery(queries.lineage);

  const openIssues = (issues.data ?? []).filter((i) => i.status !== "resolved");
  const critical = openIssues.filter((i) => i.severity === "critical" || i.severity === "high");

  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "System" }, { label: "Data Quality" }]}
        title="Data Quality"
        description="If ingestion is incomplete or stale, every downstream probability is suspect. This module is a gate, not a report."
      />

      {critical.length > 0 ? (
        <WarningBanner>
          {critical.length} unresolved high-severity issue{critical.length > 1 ? "s" : ""} in the
          current window. Candidates derived from the affected partitions are flagged rather than
          hidden.
        </WarningBanner>
      ) : null}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {(dq.data ?? []).slice(0, 4).map((d) => (
          <MetricCard
            key={d.key}
            label={d.label}
            value={d.value}
            hint={d.detail}
            tone={d.state === "healthy" ? "default" : d.state === "failed" ? "negative" : "warning"}
          />
        ))}
      </div>

      <SegmentedTabs
        tabs={tabs}
        value={tab}
        onChange={setTab}
        counts={{ Issues: openIssues.length, Coverage: coverage.data?.length ?? 0 }}
        label="Data quality sections"
      />

      {tab === "Overview" ? (
        <div className="grid gap-4 xl:grid-cols-3">
          <Panel title="Quality checks" className="xl:col-span-2" bodyClassName="">
            {dq.isLoading ? (
              <TableSkeleton rows={10} cols={4} />
            ) : (
              <TableShell>
                <THead>
                  <TH>Check</TH>
                  <TH align="right">Value</TH>
                  <TH>State</TH>
                  <TH>Detail</TH>
                </THead>
                <tbody>
                  {(dq.data ?? []).map((d) => (
                    <TRow key={d.key}>
                      <TD className="text-sm">{d.label}</TD>
                      <TD align="right">
                        <Numeric>{d.value}</Numeric>
                      </TD>
                      <TD>
                        <DataStateBadge state={d.state} />
                      </TD>
                      <TD className="text-xs text-muted-foreground">{d.detail}</TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            )}
          </Panel>

          <Panel title="Pipeline components">
            <ul className="space-y-2.5">
              {(health.data ?? []).map((h) => (
                <li key={h.component} className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm">{h.component}</div>
                    <div className="text-caption text-subtle-foreground">{h.detail}</div>
                  </div>
                  <DataStateBadge state={h.state} />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      ) : null}

      {tab === "Coverage" ? <CoverageTable /> : null}
      {tab === "Issues" ? <IssuesTable /> : null}

      {tab === "Lineage" ? (
        <Panel
          title="Data lineage"
          subtitle="Provider → ingestion → normalisation → features → analytical layer. Each node carries its own health."
        >
          {lineage.isLoading ? (
            <TableSkeleton rows={3} cols={4} />
          ) : (
            <LineageChain nodes={lineage.data ?? []} />
          )}
        </Panel>
      ) : null}
    </div>
  );
}

function CoverageTable() {
  const coverage = useQuery(queries.coverage);
  const rows = coverage.data ?? [];
  return (
    <Panel
      title="Coverage by competition"
      subtitle="Fixture, odds and market coverage against the competition calendar."
      bodyClassName=""
      actions={<StatusBadge tone="warning">Demo data</StatusBadge>}
    >
      {coverage.isLoading ? (
        <TableSkeleton rows={6} cols={7} />
      ) : (
        <TableShell>
          <THead>
            <TH>Competition</TH>
            <TH align="right">Fixtures</TH>
            <TH align="right">Odds coverage</TH>
            <TH align="right">Markets coverage</TH>
            <TH align="right">Books</TH>
            <TH>Last capture</TH>
            <TH>Freshness</TH>
            <TH>State</TH>
          </THead>
          <tbody>
            {rows.map((c) => (
              <TRow key={c.competitionId}>
                <TD>
                  <div className="text-sm">{c.competition}</div>
                  <div className="text-caption text-subtle-foreground">{c.code}</div>
                </TD>
                <TD align="right">
                  <Numeric muted>{c.fixtures}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric className={c.oddsCoverage < 0.7 ? "text-warning" : ""}>
                    {pct(c.oddsCoverage, 0)}
                  </Numeric>
                </TD>
                <TD align="right">
                  <Numeric>{pct(c.marketsCoverage, 0)}</Numeric>
                </TD>
                <TD align="right">
                  <Numeric muted>{c.bookmakers}</Numeric>
                </TD>
                <TD>
                  <Numeric muted>{dateTimeOf(c.lastCapture)}</Numeric>
                </TD>
                <TD>
                  <FreshnessBadge freshness={c.freshness} />
                </TD>
                <TD>
                  <DataStateBadge state={c.state} />
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
    </Panel>
  );
}

function IssuesTable() {
  const issues = useQuery(queries.issues);
  const [severity, setSeverity] = useState("all");
  const [status, setStatus] = useState("open");

  const rows = useMemo(
    () =>
      (issues.data ?? []).filter((i) => {
        if (severity !== "all" && i.severity !== severity) return false;
        if (status === "open" && i.status === "resolved") return false;
        if (status !== "all" && status !== "open" && i.status !== status) return false;
        return true;
      }),
    [issues.data, severity, status],
  );

  return (
    <div className="space-y-4">
      <FilterBar
        onReset={() => {
          setSeverity("all");
          setStatus("open");
        }}
        meta={
          <span className="numeric text-caption text-subtle-foreground">{rows.length} issues</span>
        }
      >
        <SelectFilter
          label="Severity"
          value={severity}
          onChange={setSeverity}
          options={[
            { value: "all", label: "All severities" },
            { value: "critical", label: "Critical" },
            { value: "high", label: "High" },
            { value: "medium", label: "Medium" },
            { value: "low", label: "Low" },
          ]}
        />
        <SelectFilter
          label="Status"
          value={status}
          onChange={setStatus}
          options={[
            { value: "open", label: "Unresolved" },
            { value: "investigating", label: "Investigating" },
            { value: "monitoring", label: "Monitoring" },
            { value: "resolved", label: "Resolved" },
            { value: "all", label: "All" },
          ]}
        />
      </FilterBar>

      <Panel bodyClassName="">
        {issues.isLoading ? (
          <TableSkeleton rows={6} cols={6} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="No issues in this selection"
            description="Nothing matches the current severity and status filters for the active window."
          />
        ) : (
          <TableShell>
            <THead>
              <TH>Issue</TH>
              <TH>Severity</TH>
              <TH>Entity</TH>
              <TH>Detected</TH>
              <TH>Status</TH>
              <TH>Detail</TH>
            </THead>
            <tbody>
              {rows.map((i) => (
                <TRow key={i.id}>
                  <TD className="text-sm">{i.type}</TD>
                  <TD>
                    <SeverityBadge severity={i.severity} />
                  </TD>
                  <TD className="numeric text-xs text-muted-foreground">{i.entity}</TD>
                  <TD>
                    <Numeric muted>{dateTimeOf(i.detectedAt)}</Numeric>
                  </TD>
                  <TD className="text-xs capitalize text-muted-foreground">{i.status}</TD>
                  <TD className="max-w-md text-xs text-muted-foreground">{i.detail}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
    </div>
  );
}
