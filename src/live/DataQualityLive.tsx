import { useState } from "react";
import { t } from "@/lib/i18n";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { SeverityBadge } from "@/components/system/Timelines";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { QualitySnapshot } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { ratio, relative, utcDateTime } from "./format";
import { JobsPanel, RunsPanel } from "./RunsPanel";

const tabs = ["Issues", "Coverage", "Jobs", "Ingestion runs", "Notes"] as const;
type Tab = (typeof tabs)[number];

/** A metric card whose value may be null for a stated reason. */
function Metric({
  label,
  value,
  why,
  hint,
  tone = "default",
}: {
  label: string;
  value: string | null;
  why?: string | undefined;
  hint: string;
  tone?: "default" | "positive" | "negative" | "warning" | "muted";
}) {
  return (
    <div className="surface-panel px-4 py-3">
      <div className="text-label text-subtle-foreground">{label}</div>
      <div className="mt-1.5 numeric-lg">
        {value === null ? (
          <Nullable value={null} reason={why ?? "Not computable."} />
        ) : (
          <span
            className={
              tone === "negative"
                ? "text-negative"
                : tone === "warning"
                  ? "text-warning"
                  : tone === "positive"
                    ? "text-positive"
                    : tone === "muted"
                      ? "text-muted-foreground"
                      : "text-foreground"
            }
          >
            {value}
          </span>
        )}
      </div>
      <div className="mt-1 text-caption text-muted-foreground">{hint}</div>
    </div>
  );
}

function Cards({ s, why }: { s: QualitySnapshot; why: Record<string, string> }) {
  const warn = (n: number) => (n > 0 ? "warning" : "default");
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Metric
        label="Fixtures expected"
        value={int(s.fixtures_expected)}
        hint={`Scheduled, tracked competitions, next ${s.horizon_hours} h`}
      />
      <Metric
        label="Fixtures with odds"
        value={int(s.fixtures_with_odds)}
        hint={`${int(s.fixtures_with_near_close)} with a near-close capture`}
      />
      <Metric
        label="Odds coverage"
        value={ratio(s.fixture_odds_coverage)}
        why={why["fixture_odds_coverage"]}
        hint="Expected fixtures with at least one snapshot"
      />
      <Metric
        label="Capture windows (24 h)"
        value={ratio(s.window_coverage_24h)}
        why={why["window_coverage_24h"]}
        hint={`${s.windows_captured_24h} of ${s.windows_expected_24h} windows for fixtures that kicked off`}
      />
      <Metric
        label="Bookmakers seen (24 h)"
        value={`${s.bookmakers_seen_24h} / ${s.bookmakers_active}`}
        hint={`Coverage ${ratio(s.bookmaker_coverage) ?? "—"} of active bookmakers`}
        tone={s.bookmakers_seen_24h === 0 ? "muted" : "default"}
      />
      <Metric
        label="Markets seen (24 h)"
        value={`${s.markets_seen_24h} / ${s.markets_tracked}`}
        hint={`Coverage ${ratio(s.market_coverage) ?? "—"} of tracked markets`}
        tone={s.markets_seen_24h === 0 ? "muted" : "default"}
      />
      <Metric
        label="Snapshots (24 h)"
        value={int(s.snapshots_24h)}
        hint={
          s.last_successful_capture
            ? `Last capture ${relative(s.last_successful_capture)}`
            : (why["last_successful_capture"] ?? "")
        }
        tone={s.snapshots_24h === 0 ? "muted" : "default"}
      />
      <Metric
        label="Stale fixtures"
        value={int(s.stale_fixtures)}
        hint="Upcoming, newest snapshot older than 4 h"
        tone={warn(s.stale_fixtures)}
      />
      <Metric
        label="Awaiting result"
        value={int(s.fixtures_awaiting_result)}
        hint={`${int(s.fixtures_with_result)} past fixtures have a score`}
        tone={warn(s.fixtures_awaiting_result)}
      />
      <Metric
        label="Partial jobs (24 h)"
        value={int(s.partial_jobs_24h)}
        hint="Wrote something and hit errors"
        tone={warn(s.partial_jobs_24h)}
      />
      <Metric
        label="Failed jobs (24 h)"
        value={int(s.failed_jobs_24h)}
        hint="Errors and nothing durable, or stopped at a cap"
        tone={s.failed_jobs_24h ? "negative" : "default"}
      />
      <Metric
        label="Provider errors (24 h)"
        value={int(s.provider_errors_24h)}
        hint="Refusals and failures recorded by runs"
        tone={warn(s.provider_errors_24h)}
      />
      <Metric
        label="Requests today"
        value={`${s.requests_today} / ${s.daily_budget}`}
        hint={`${s.requests_remaining_today} remaining · ${s.unattributed_requests_today} not claimed by a closed run`}
        tone={s.requests_remaining_today === 0 ? "negative" : "default"}
      />
      <Metric
        label="Runs stuck"
        value={int(s.stale_running_jobs)}
        hint="'running' for over 2 h: the owner likely died"
        tone={s.stale_running_jobs ? "negative" : "default"}
      />
    </div>
  );
}

export function DataQualityLive() {
  const [tab, setTab] = useState<Tab>("Issues");
  const quality = useLiveQuery(live.quality);
  const issues = useLiveQuery(live.issues);
  const coverage = useLiveQuery(live.coverage);
  const runs = useLiveQuery(live.runs);
  const jobs = useLiveQuery(live.jobs);

  const high = (issues.data?.data ?? []).filter(
    (i) => i.severity === "critical" || i.severity === "high",
  );
  const s = quality.data?.data.snapshot;

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.dataQuality.title")}
        description={t("admin.pages.dataQuality.description")}
      />

      {quality.isError ? <ApiErrorNotice error={quality.error} /> : null}

      {high.length > 0 ? (
        <WarningBanner>
          {high.length} high-severity issue{high.length > 1 ? "s" : ""} detected in the data right
          now: {high.map((i) => i.title.toLowerCase()).join("; ")}.
        </WarningBanner>
      ) : null}

      {s && quality.data ? (
        <Cards s={s} why={quality.data.data.explanations} />
      ) : !quality.isError ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <MetricCard key={i} label="Loading" value={null} tone="muted" />
          ))}
        </div>
      ) : null}

      <SegmentedTabs
        label="Data quality sections"
        tabs={tabs}
        value={tab}
        onChange={setTab}
        counts={{
          Issues: issues.data?.data.length ?? 0,
          Coverage: coverage.data?.data.length ?? 0,
        }}
      />

      {tab === "Issues" ? (
        <Panel
          title="Issues"
          subtitle="Derived from the data on every request - there is no list to go stale"
          bodyClassName=""
        >
          {issues.isLoading ? (
            <TableSkeleton rows={4} cols={4} />
          ) : issues.isError ? (
            <div className="p-4">
              <ApiErrorNotice error={issues.error} />
            </div>
          ) : issues.data && issues.data.status !== "ok" ? (
            <StatusNotice status={issues.data.status} reason={issues.data.reason} />
          ) : (
            <TableShell>
              <THead>
                <TH>Severity</TH>
                <TH>Issue</TH>
                <TH align="right">Count</TH>
                <TH>Detected</TH>
              </THead>
              <tbody>
                {(issues.data?.data ?? []).map((i) => (
                  <TRow key={i.key}>
                    <TD>
                      <SeverityBadge severity={i.severity} />
                    </TD>
                    <TD>
                      <div className="text-sm">{i.title}</div>
                      <div className="max-w-xl text-caption text-muted-foreground">{i.detail}</div>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(i.count)}</Numeric>
                    </TD>
                    <TD>
                      <Numeric muted>{utcDateTime(i.detected_at)}</Numeric>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
      ) : null}

      {tab === "Coverage" ? (
        <Panel
          title="Coverage by competition"
          subtitle="Tracked competitions, current season"
          bodyClassName=""
        >
          {coverage.isError ? (
            <div className="p-4">
              <ApiErrorNotice error={coverage.error} />
            </div>
          ) : coverage.data && coverage.data.status !== "ok" ? (
            <StatusNotice status={coverage.data.status} reason={coverage.data.reason} />
          ) : (
            <TableShell>
              <THead>
                <TH>Competition</TH>
                <TH align="right">In horizon</TH>
                <TH align="right">With odds</TH>
                <TH align="right">Coverage</TH>
                <TH align="right">Bookmakers 24 h</TH>
                <TH align="right">Markets 24 h</TH>
                <TH>Last capture</TH>
                <TH align="right">Awaiting result</TH>
              </THead>
              <tbody>
                {(coverage.data?.data ?? []).map((c) => (
                  <TRow key={c.competition_id}>
                    <TD>
                      <div className="text-sm">{c.competition}</div>
                      <div className="numeric text-caption text-subtle-foreground">
                        season {c.season}
                      </div>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(c.fixtures_in_horizon)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(c.fixtures_with_odds)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Nullable
                        value={ratio(c.odds_coverage)}
                        reason="No scheduled fixture of this competition in the evaluation horizon: nothing to cover."
                        className="numeric"
                      />
                    </TD>
                    <TD align="right">
                      <Numeric>{int(c.bookmakers_seen_24h)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(c.markets_seen_24h)}</Numeric>
                    </TD>
                    <TD>
                      <Nullable
                        value={c.last_capture_at ? utcDateTime(c.last_capture_at) : null}
                        reason="No snapshot has ever been captured for this competition."
                        className="numeric text-xs"
                      />
                    </TD>
                    <TD align="right">
                      <Numeric className={c.fixtures_awaiting_result ? "text-warning" : ""}>
                        {int(c.fixtures_awaiting_result)}
                      </Numeric>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
      ) : null}

      {tab === "Jobs" ? (
        jobs.isError ? (
          <ApiErrorNotice error={jobs.error} />
        ) : (
          <JobsPanel jobs={jobs.data?.data ?? []} />
        )
      ) : null}

      {tab === "Ingestion runs" ? (
        runs.isError ? (
          <ApiErrorNotice error={runs.error} />
        ) : (
          <RunsPanel runs={runs.data?.data ?? []} />
        )
      ) : null}

      {tab === "Notes" ? (
        <Panel title="Notes" subtitle="What the snapshot itself flags">
          {s && s.notes.length > 0 ? (
            <ul className="list-disc space-y-1.5 pl-5 text-xs text-muted-foreground">
              {s.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : (
            <StatusNotice status="empty" reason="The snapshot raises no note." compact />
          )}
        </Panel>
      ) : null}
    </div>
  );
}
