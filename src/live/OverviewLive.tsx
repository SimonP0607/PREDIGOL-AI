import { Link } from "@tanstack/react-router";
import { getTimeZone, zoneAbbrev } from "@/lib/time";
import { t, translateOr } from "@/lib/i18n";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { ComponentHealth, Overview } from "@/lib/api/v1/types";
import { cn } from "@/lib/utils";
import { int } from "@/lib/format";
import { durationMs, isoDay, relative, utcDate, utcDateTime } from "./format";
import { ComponentStatusBadge, FixtureLink, StatusGroupBadge } from "./shared";
import { RunsPanel } from "./RunsPanel";
import { healthReason, jobLabel } from "./labels";

function firstProblem(o: Overview): ComponentHealth | null {
  const parts = [o.system.database, o.system.worker, o.system.football_provider];
  return parts.find((p) => p.status === "down") ?? parts.find((p) => p.status !== "ok") ?? null;
}

export function OverviewLive() {
  const overview = useLiveQuery(live.overview);
  const today = isoDay(new Date());
  const upcoming = useLiveQuery(
    live.matches({ date_from: today, status: "scheduled", order: "asc", limit: 10 }),
  );

  if (overview.isError) {
    return (
      <div className="space-y-5">
        <PageHeader
          title={t("admin.pages.overview.title")}
          description={t("admin.pages.overview.description")}
        />
        <ApiErrorNotice error={overview.error} />
      </div>
    );
  }
  const o = overview.data?.data;
  const problem = o ? firstProblem(o) : null;

  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.overview.title")}
        description={t("admin.pages.overview.description")}
        actions={<StatusBadge tone="brand">{t("ops.overview.shadowMode")}</StatusBadge>}
      />

      <dl className="surface-panel grid grid-cols-2 divide-border sm:grid-cols-4 sm:divide-x">
        <Cell
          label={t("ops.overview.cells.today")}
          value={o ? utcDate(overview.data?.meta.generated_at) : null}
          hint={`${getTimeZone()} · ${zoneAbbrev()}`}
        />
        <Cell
          label={t("ops.overview.cells.fixtures")}
          value={o ? int(o.database.fixtures) : null}
          hint={
            o
              ? t("ops.overview.cells.fixturesHint", {
                  upcoming: o.fixtures.upcoming_7d,
                  count: o.database.competitions_tracked,
                })
              : ""
          }
        />
        <Cell
          label={t("ops.overview.cells.lastPayload")}
          value={
            o
              ? o.freshness.last_payload_at
                ? relative(o.freshness.last_payload_at)
                : t("ops.overview.cells.never")
              : null
          }
          hint={
            o
              ? t("ops.overview.cells.syncs", {
                  fixtures: relative(o.freshness.last_fixtures_sync_at),
                  results: relative(o.freshness.last_results_sync_at),
                })
              : ""
          }
        />
        <Cell
          label={t("ops.overview.cells.systemState")}
          value={o ? o.system.status.toUpperCase() : null}
          hint={problem ? problem.detail : o ? t("ops.overview.cells.allOk") : ""}
          tone={
            o
              ? o.system.status === "ok"
                ? "positive"
                : o.system.status === "down"
                  ? "negative"
                  : "warning"
              : "plain"
          }
        />
      </dl>

      <WarningBanner>{t("ops.overview.banner")}</WarningBanner>

      <LiveStrip />

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel
          title={t("ops.overview.upcoming.title")}
          subtitle={t("ops.overview.upcoming.subtitle")}
          className="xl:col-span-2"
          bodyClassName=""
          actions={
            <Link to="/matches" className="text-caption text-primary hover:underline">
              {t("ops.overview.upcoming.all")}
            </Link>
          }
        >
          {upcoming.isLoading ? (
            <TableSkeleton rows={4} cols={5} />
          ) : upcoming.isError ? (
            <div className="p-4">
              <ApiErrorNotice error={upcoming.error} />
            </div>
          ) : upcoming.data && upcoming.data.status !== "ok" ? (
            <StatusNotice status={upcoming.data.status} reason={t("ops.overview.upcoming.empty")} />
          ) : (
            <TableShell className="min-w-0">
              <THead>
                <TH>{t("ops.overview.upcoming.headers.kickoff")}</TH>
                <TH>{t("ops.overview.upcoming.headers.competition")}</TH>
                <TH>{t("ops.overview.upcoming.headers.fixture")}</TH>
                <TH align="right" title={t("ops.overview.upcoming.headers.pricesHelp")}>
                  {t("ops.overview.upcoming.headers.prices")}
                </TH>
                <TH>{t("ops.overview.upcoming.headers.status")}</TH>
              </THead>
              <tbody>
                {(upcoming.data?.data ?? []).map((m) => (
                  <TRow key={m.id}>
                    <TD className="whitespace-nowrap">
                      <Numeric className="text-xs">{utcDateTime(m.kickoff_at)}</Numeric>
                    </TD>
                    <TD className="max-w-[9rem] truncate text-xs text-muted-foreground">
                      <span title={m.competition.name}>{m.competition.name}</span>
                    </TD>
                    <TD className="max-w-[18rem]">
                      <FixtureLink match={m} />
                    </TD>
                    <TD align="right">
                      <Numeric muted={m.odds.snapshots === 0}>{int(m.odds.snapshots)}</Numeric>
                    </TD>
                    <TD>
                      <StatusGroupBadge match={m} />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>

        <Panel title={t("ops.overview.health.title")} subtitle={t("ops.overview.health.subtitle")}>
          {!o ? (
            <TableSkeleton rows={4} cols={2} />
          ) : (
            <ul className="space-y-2.5">
              {(
                [
                  ["API", o.system.app],
                  [t("ops.overview.database.title"), o.system.database],
                  ["Worker", o.system.worker],
                  [t("ops.overview.health.provider"), o.system.football_provider],
                ] as const
              ).map(([label, c]) => (
                <li key={label} className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm">{label}</div>
                    <div className="text-caption text-subtle-foreground">{healthReason(c)}</div>
                  </div>
                  <ComponentStatusBadge status={c.status} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {o ? (
        <div className="grid gap-5 lg:grid-cols-3">
          <Panel title="Worker" subtitle={t("ops.overview.worker.subtitle")}>
            <KeyValue
              label={t("ops.overview.worker.alive")}
              value={
                o.worker.alive === null ? (
                  <Nullable value={null} reason={t("ops.overview.worker.neverBeat")} />
                ) : o.worker.alive ? (
                  t("ops.common.yes")
                ) : (
                  t("ops.common.no")
                )
              }
            />
            <KeyValue
              label={t("ops.overview.worker.lastBeat")}
              value={
                <Nullable
                  value={o.worker.last_beat_at ? relative(o.worker.last_beat_at) : null}
                  reason={t("ops.overview.worker.noBeat")}
                />
              }
            />
            <KeyValue
              label={t("ops.overview.worker.runningSince")}
              value={
                <Nullable
                  value={o.worker.started_at ? utcDateTime(o.worker.started_at) : null}
                  reason={t("ops.overview.worker.noBeat")}
                />
              }
            />
            <KeyValue label={t("ops.overview.worker.ticks")} value={int(o.worker.ticks)} />
            <KeyValue
              label={t("ops.overview.worker.lastTick")}
              value={
                <Nullable
                  value={
                    o.worker.last_tick_outcome ? tickOutcome(o.worker.last_tick_outcome) : null
                  }
                  reason={t("ops.overview.worker.noTick")}
                />
              }
            />
            <KeyValue
              label={t("ops.overview.worker.lag")}
              value={
                <Nullable
                  value={
                    o.worker.scheduler_lag_ms === null
                      ? null
                      : durationMs(o.worker.scheduler_lag_ms)
                  }
                  reason={t("ops.overview.worker.lagPending")}
                />
              }
            />
            {Object.entries(o.worker.next_runs).map(([job, at]) => (
              <KeyValue
                key={job}
                label={t("ops.overview.worker.next", { job: jobLabel(job) })}
                value={at ? relative(at) : "—"}
              />
            ))}
            <KeyValue label={t("ops.overview.worker.code")} value={o.worker.code_version ?? "—"} />
          </Panel>

          <Panel
            title={t("ops.overview.provider.title")}
            subtitle={t("ops.overview.provider.subtitle")}
          >
            <MetricCard
              label={t("ops.overview.provider.requestsToday")}
              value={`${int(o.provider.requests_today)} / ${int(o.provider.daily_budget)}`}
              hint={t("ops.overview.provider.requestsHint", {
                remaining: o.provider.requests_remaining,
                plan: o.provider.plan,
                limit: int(o.provider.plan_daily_limit),
              })}
              tone={o.provider.requests_remaining === 0 ? "negative" : "default"}
            />
            <div className="mt-3">
              <KeyValue
                label={t("ops.overview.provider.lastError")}
                value={
                  <Nullable
                    value={o.provider.last_error_at ? relative(o.provider.last_error_at) : null}
                    reason={t("ops.overview.provider.noError")}
                  />
                }
              />
              {o.provider.last_error ? (
                <p className="mt-1.5 break-words text-caption text-muted-foreground">
                  {o.provider.last_error}
                </p>
              ) : null}
            </div>
          </Panel>

          <Panel
            title={t("ops.overview.database.title")}
            subtitle={t("ops.overview.database.subtitle", { revision: o.database.revision })}
          >
            <KeyValue
              label={t("ops.overview.database.competitions")}
              value={t("ops.overview.database.competitionsValue", {
                tracked: int(o.database.competitions_tracked),
                known: int(o.database.competitions_known),
              })}
            />
            <KeyValue label={t("ops.overview.database.teams")} value={int(o.database.teams)} />
            <KeyValue
              label={t("ops.overview.database.fixtures")}
              value={int(o.database.fixtures)}
            />
            <KeyValue
              label={t("ops.overview.database.withResult")}
              value={int(o.database.fixtures_with_result)}
            />
            <KeyValue
              label={t("ops.overview.database.awaitingResult")}
              value={int(o.fixtures.awaiting_result)}
            />
            <KeyValue
              label={t("ops.overview.database.oddsSnapshots")}
              value={int(o.database.odds_snapshots)}
            />
            <KeyValue
              label={t("ops.overview.database.nearClose")}
              value={int(o.database.near_close_snapshots)}
            />
            <KeyValue
              label={t("ops.overview.database.rawPayloads")}
              value={int(o.database.raw_payloads)}
            />
            <KeyValue
              label={t("ops.overview.database.predictions")}
              value={int(o.database.predictions)}
            />
          </Panel>
        </div>
      ) : null}

      {o ? <RunsPanel runs={o.recent_runs} /> : null}

      {o ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Picks" subtitle={t("ops.overview.picks.subtitle")}>
            <SectionView section={o.picks}>
              {(d) => <KeyValue label="Picks" value={int(d?.["picks"] ?? 0)} />}
            </SectionView>
          </Panel>
          <Panel
            title={t("ops.overview.performance.title")}
            subtitle={t("ops.overview.performance.subtitle")}
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricCard
                label={t("ops.overview.performance.pnl")}
                value={null}
                tone="muted"
                hint={t("ops.overview.performance.pnlHint")}
              />
              <MetricCard
                label="ROI"
                value={null}
                tone="muted"
                hint={t("ops.overview.performance.roiHint")}
              />
            </div>
            <StatusNotice
              status={o.performance.status}
              reason={o.performance.reason}
              compact
              className="mt-3"
            />
          </Panel>
        </div>
      ) : null}
    </div>
  );
}

function Cell({
  label,
  value,
  hint,
  tone = "plain",
}: {
  label: string;
  value: string | null;
  hint: string;
  tone?: "plain" | "positive" | "warning" | "negative";
}) {
  return (
    <div className="px-4 py-3">
      <dt className="text-label text-subtle-foreground">{label}</dt>
      <dd
        className={cn(
          "numeric mt-1 flex items-center gap-1.5 text-base",
          tone === "warning" && "text-warning",
          tone === "negative" && "text-negative",
          tone === "positive" && "text-positive",
        )}
      >
        {tone !== "plain" ? (
          <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-current" />
        ) : null}
        {value ?? <span className="h-4 w-20 animate-pulse rounded bg-muted" />}
      </dd>
      <dd className="mt-0.5 text-caption text-muted-foreground">{hint}</dd>
    </div>
  );
}

/** Matches in play right now, from GET /live - a door to the Live page. */
function LiveStrip() {
  const q = useLiveQuery(live.liveBoard);
  const matches = q.data?.data.matches ?? [];
  if (!q.data || q.isError) return null;
  return (
    <Panel
      title={
        matches.length
          ? t("ops.overview.live.titleCount", { n: matches.length })
          : t("ops.overview.live.title")
      }
      subtitle={t("ops.overview.live.subtitle")}
      actions={
        <Link to="/live" className="text-caption text-primary hover:underline">
          {t("ops.overview.live.link")}
        </Link>
      }
      bodyClassName={matches.length ? "p-0" : "p-4"}
    >
      {matches.length ? (
        <ul className="grid divide-y divide-border sm:grid-cols-2 sm:divide-y-0 xl:grid-cols-3">
          {matches.slice(0, 9).map((m) => (
            <li key={m.fixture_id} className="min-w-0 border-border sm:border-b">
              <Link
                to="/matches/$fixtureId"
                params={{ fixtureId: String(m.fixture_id) }}
                className="flex items-center justify-between gap-3 px-4 py-2.5 hover:bg-muted/40"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm">
                    {m.home.name}{" "}
                    <span className="text-subtle-foreground">{t("ops.overview.live.versus")}</span>{" "}
                    {m.away.name}
                  </span>
                  <span className="block truncate text-caption text-muted-foreground">
                    {m.competition}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="numeric text-sm">
                    {m.goals_home ?? "?"}–{m.goals_away ?? "?"}
                  </span>
                  <StatusBadge tone="brand">
                    {m.status === "HT" ? "HT" : m.elapsed !== null ? `${m.elapsed}'` : m.status}
                  </StatusBadge>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted-foreground">
          {q.data.status === "empty" || !q.data.reason
            ? t("ops.overview.live.empty")
            : q.data.reason}
        </p>
      )}
    </Panel>
  );
}

/** The worker's last tick, in the reader's language ("nothing_due" -> "nada pendiente"). */
function tickOutcome(outcome: string): string {
  return translateOr(`ops.overview.worker.outcomes.${outcome}`, outcome.replaceAll("_", " "));
}
