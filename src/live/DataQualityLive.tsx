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

/** A tab's text in the reader's language; the tab value itself stays the state key. */
function tabLabel(tab: Tab): string {
  switch (tab) {
    case "Issues":
      return t("system.dataQuality.tabs.issues");
    case "Coverage":
      return t("system.dataQuality.tabs.coverage");
    case "Jobs":
      return t("system.dataQuality.tabs.jobs");
    case "Ingestion runs":
      return t("system.dataQuality.tabs.runs");
    case "Notes":
      return t("system.dataQuality.tabs.notes");
  }
}

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
          <Nullable value={null} reason={why ?? t("system.dataQuality.notComputable")} />
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
        label={t("system.dataQuality.cards.fixturesExpected.label")}
        value={int(s.fixtures_expected)}
        hint={t("system.dataQuality.cards.fixturesExpected.hint", { hours: s.horizon_hours })}
      />
      <Metric
        label={t("system.dataQuality.cards.fixturesWithOdds.label")}
        value={int(s.fixtures_with_odds)}
        hint={t("system.dataQuality.cards.fixturesWithOdds.hint", {
          n: int(s.fixtures_with_near_close),
        })}
      />
      <Metric
        label={t("system.dataQuality.cards.oddsCoverage.label")}
        value={ratio(s.fixture_odds_coverage)}
        why={why["fixture_odds_coverage"]}
        hint={t("system.dataQuality.cards.oddsCoverage.hint")}
      />
      <Metric
        label={t("system.dataQuality.cards.captureWindows.label")}
        value={ratio(s.window_coverage_24h)}
        why={why["window_coverage_24h"]}
        hint={t("system.dataQuality.cards.captureWindows.hint", {
          captured: s.windows_captured_24h,
          expected: s.windows_expected_24h,
        })}
      />
      <Metric
        label={t("system.dataQuality.cards.bookmakersSeen.label")}
        value={`${s.bookmakers_seen_24h} / ${s.bookmakers_active}`}
        hint={t("system.dataQuality.cards.bookmakersSeen.hint", {
          ratio: ratio(s.bookmaker_coverage) ?? "—",
        })}
        tone={s.bookmakers_seen_24h === 0 ? "muted" : "default"}
      />
      <Metric
        label={t("system.dataQuality.cards.marketsSeen.label")}
        value={`${s.markets_seen_24h} / ${s.markets_tracked}`}
        hint={t("system.dataQuality.cards.marketsSeen.hint", {
          ratio: ratio(s.market_coverage) ?? "—",
        })}
        tone={s.markets_seen_24h === 0 ? "muted" : "default"}
      />
      <Metric
        label={t("system.dataQuality.cards.snapshots.label")}
        value={int(s.snapshots_24h)}
        hint={
          s.last_successful_capture
            ? t("system.dataQuality.cards.snapshots.hint", {
                when: relative(s.last_successful_capture),
              })
            : (why["last_successful_capture"] ?? "")
        }
        tone={s.snapshots_24h === 0 ? "muted" : "default"}
      />
      <Metric
        label={t("system.dataQuality.cards.staleFixtures.label")}
        value={int(s.stale_fixtures)}
        hint={t("system.dataQuality.cards.staleFixtures.hint")}
        tone={warn(s.stale_fixtures)}
      />
      <Metric
        label={t("system.dataQuality.cards.awaitingResult.label")}
        value={int(s.fixtures_awaiting_result)}
        hint={t("system.dataQuality.cards.awaitingResult.hint", {
          n: int(s.fixtures_with_result),
        })}
        tone={warn(s.fixtures_awaiting_result)}
      />
      <Metric
        label={t("system.dataQuality.cards.partialJobs.label")}
        value={int(s.partial_jobs_24h)}
        hint={t("system.dataQuality.cards.partialJobs.hint")}
        tone={warn(s.partial_jobs_24h)}
      />
      <Metric
        label={t("system.dataQuality.cards.failedJobs.label")}
        value={int(s.failed_jobs_24h)}
        hint={t("system.dataQuality.cards.failedJobs.hint")}
        tone={s.failed_jobs_24h ? "negative" : "default"}
      />
      <Metric
        label={t("system.dataQuality.cards.providerErrors.label")}
        value={int(s.provider_errors_24h)}
        hint={t("system.dataQuality.cards.providerErrors.hint")}
        tone={warn(s.provider_errors_24h)}
      />
      <Metric
        label={t("system.dataQuality.cards.requestsToday.label")}
        value={`${s.requests_today} / ${s.daily_budget}`}
        hint={t("system.dataQuality.cards.requestsToday.hint", {
          remaining: s.requests_remaining_today,
          unclaimed: s.unattributed_requests_today,
        })}
        tone={s.requests_remaining_today === 0 ? "negative" : "default"}
      />
      <Metric
        label={t("system.dataQuality.cards.runsStuck.label")}
        value={int(s.stale_running_jobs)}
        hint={t("system.dataQuality.cards.runsStuck.hint")}
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
          {t("system.dataQuality.highIssues", {
            count: high.length,
            titles: high.map((i) => i.title.toLowerCase()).join("; "),
          })}
        </WarningBanner>
      ) : null}

      {s && quality.data ? (
        <Cards s={s} why={quality.data.data.explanations} />
      ) : !quality.isError ? (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }, (_, i) => (
            <MetricCard key={i} label={t("system.dataQuality.loading")} value={null} tone="muted" />
          ))}
        </div>
      ) : null}

      <SegmentedTabs
        label={t("system.dataQuality.sections")}
        tabs={tabs}
        value={tab}
        onChange={setTab}
        format={tabLabel}
        counts={{
          Issues: issues.data?.data.length ?? 0,
          Coverage: coverage.data?.data.length ?? 0,
        }}
      />

      {tab === "Issues" ? (
        <Panel
          title={t("system.dataQuality.issues.title")}
          subtitle={t("system.dataQuality.issues.subtitle")}
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
                <TH>{t("system.dataQuality.issues.headers.severity")}</TH>
                <TH>{t("system.dataQuality.issues.headers.issue")}</TH>
                <TH align="right">{t("system.dataQuality.issues.headers.count")}</TH>
                <TH>{t("system.dataQuality.issues.headers.detected")}</TH>
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
          title={t("system.dataQuality.coverage.title")}
          subtitle={t("system.dataQuality.coverage.subtitle")}
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
                <TH>{t("system.dataQuality.coverage.headers.competition")}</TH>
                <TH align="right">{t("system.dataQuality.coverage.headers.inHorizon")}</TH>
                <TH align="right">{t("system.dataQuality.coverage.headers.withOdds")}</TH>
                <TH align="right">{t("system.dataQuality.coverage.headers.coverage")}</TH>
                <TH align="right">{t("system.dataQuality.coverage.headers.bookmakers24h")}</TH>
                <TH align="right">{t("system.dataQuality.coverage.headers.markets24h")}</TH>
                <TH>{t("system.dataQuality.coverage.headers.lastCapture")}</TH>
                <TH align="right">{t("system.dataQuality.coverage.headers.awaitingResult")}</TH>
              </THead>
              <tbody>
                {(coverage.data?.data ?? []).map((c) => (
                  <TRow key={c.competition_id}>
                    <TD>
                      <div className="text-sm">{c.competition}</div>
                      <div className="numeric text-caption text-subtle-foreground">
                        {t("system.dataQuality.coverage.season", { season: c.season })}
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
                        reason={t("system.dataQuality.coverage.noFixture")}
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
                        reason={t("system.dataQuality.coverage.noSnapshot")}
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
        <Panel
          title={t("system.dataQuality.notes.title")}
          subtitle={t("system.dataQuality.notes.subtitle")}
        >
          {s && s.notes.length > 0 ? (
            <ul className="list-disc space-y-1.5 pl-5 text-xs text-muted-foreground">
              {s.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          ) : (
            <StatusNotice status="empty" reason={t("system.dataQuality.notes.empty")} compact />
          )}
        </Panel>
      ) : null}
    </div>
  );
}
