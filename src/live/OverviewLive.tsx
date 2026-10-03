import { Link } from "@tanstack/react-router";
import { getTimeZone, zoneAbbrev } from "@/lib/time";
import { t } from "@/lib/i18n";
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
import { JOB_LABEL } from "./labels";

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
        actions={<StatusBadge tone="brand">Shadow mode</StatusBadge>}
      />

      <dl className="surface-panel grid grid-cols-2 divide-border sm:grid-cols-4 sm:divide-x">
        <Cell
          label="Today"
          value={o ? utcDate(overview.data?.meta.generated_at) : null}
          hint={`${getTimeZone()} · ${zoneAbbrev()}`}
        />
        <Cell
          label="Fixtures stored"
          value={o ? int(o.database.fixtures) : null}
          hint={
            o
              ? `${o.fixtures.upcoming_7d} upcoming in 7 days · ${o.database.competitions_tracked} tracked competition(s)`
              : ""
          }
        />
        <Cell
          label="Last payload"
          value={
            o
              ? o.freshness.last_payload_at
                ? relative(o.freshness.last_payload_at)
                : "never"
              : null
          }
          hint={
            o
              ? `Fixtures sync ${relative(o.freshness.last_fixtures_sync_at)} · results ${relative(o.freshness.last_results_sync_at)}`
              : ""
          }
        />
        <Cell
          label="System state"
          value={o ? o.system.status.toUpperCase() : null}
          hint={problem ? problem.detail : o ? "All components report ok" : ""}
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

      <WarningBanner>
        Research / shadow mode. Picks are recorded in shadow only: nothing is published and nothing
        is bet. What they would have done is measured in Performance.
      </WarningBanner>

      <LiveStrip />

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel
          title="Upcoming matches"
          subtitle="Scheduled fixtures of the competitions the capturer tracks"
          className="xl:col-span-2"
          bodyClassName=""
          actions={
            <Link to="/matches" className="text-caption text-primary hover:underline">
              All matches
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
            <StatusNotice
              status={upcoming.data.status}
              reason="No scheduled fixture is stored for today or later. The worker syncs the tracked competitions' fixtures every 12 hours."
            />
          ) : (
            <TableShell className="min-w-0">
              <THead>
                <TH>Kick-off</TH>
                <TH>Competition</TH>
                <TH>Fixture</TH>
                <TH align="right" title="Pre-match price snapshots captured so far">
                  Prices
                </TH>
                <TH>Status</TH>
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

        <Panel title="System health" subtitle="From /health: never spends provider quota">
          {!o ? (
            <TableSkeleton rows={4} cols={2} />
          ) : (
            <ul className="space-y-2.5">
              {(
                [
                  ["API", o.system.app],
                  ["Database", o.system.database],
                  ["Worker", o.system.worker],
                  ["Football provider", o.system.football_provider],
                ] as const
              ).map(([label, c]) => (
                <li key={label} className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-sm">{label}</div>
                    <div className="text-caption text-subtle-foreground">{c.detail}</div>
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
          <Panel title="Worker" subtitle="Liveness from its heartbeat, written on every tick">
            <KeyValue
              label="Alive"
              value={
                o.worker.alive === null ? (
                  <Nullable
                    value={null}
                    reason="No heartbeat has ever been written: the worker has not run with this version."
                  />
                ) : o.worker.alive ? (
                  "yes"
                ) : (
                  "no"
                )
              }
            />
            <KeyValue
              label="Last beat"
              value={
                <Nullable
                  value={o.worker.last_beat_at ? relative(o.worker.last_beat_at) : null}
                  reason="No heartbeat yet."
                />
              }
            />
            <KeyValue
              label="Running since"
              value={
                <Nullable
                  value={o.worker.started_at ? utcDateTime(o.worker.started_at) : null}
                  reason="No heartbeat yet."
                />
              }
            />
            <KeyValue label="Ticks" value={int(o.worker.ticks)} />
            <KeyValue
              label="Last tick"
              value={
                <Nullable
                  value={o.worker.last_tick_outcome?.replaceAll("_", " ") ?? null}
                  reason="No tick has run since the worker started."
                />
              }
            />
            <KeyValue
              label="Scheduler lag"
              value={
                <Nullable
                  value={
                    o.worker.scheduler_lag_ms === null
                      ? null
                      : durationMs(o.worker.scheduler_lag_ms)
                  }
                  reason="Measured on the first tick."
                />
              }
            />
            {Object.entries(o.worker.next_runs).map(([job, at]) => (
              <KeyValue
                key={job}
                label={`Next ${JOB_LABEL[job] ?? job}`}
                value={at ? relative(at) : "—"}
              />
            ))}
            <KeyValue label="Code" value={o.worker.code_version ?? "—"} />
          </Panel>

          <Panel
            title="Provider & quota"
            subtitle="Our budget, counted in the database before each request"
          >
            <MetricCard
              label="Requests today"
              value={`${o.provider.requests_today} / ${o.provider.daily_budget}`}
              hint={`${o.provider.requests_remaining} remaining · plan ${o.provider.plan} allows ${int(o.provider.plan_daily_limit)}/day`}
              tone={o.provider.requests_remaining === 0 ? "negative" : "default"}
            />
            <div className="mt-3">
              <KeyValue
                label="Last provider error"
                value={
                  <Nullable
                    value={o.provider.last_error_at ? relative(o.provider.last_error_at) : null}
                    reason="No run has recorded a provider error."
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

          <Panel title="Database" subtitle={`Schema revision ${o.database.revision}`}>
            <KeyValue
              label="Competitions"
              value={`${int(o.database.competitions_tracked)} tracked / ${int(o.database.competitions_known)} known`}
            />
            <KeyValue label="Teams" value={int(o.database.teams)} />
            <KeyValue label="Fixtures" value={int(o.database.fixtures)} />
            <KeyValue label="With result" value={int(o.database.fixtures_with_result)} />
            <KeyValue label="Awaiting result" value={int(o.fixtures.awaiting_result)} />
            <KeyValue label="Odds snapshots" value={int(o.database.odds_snapshots)} />
            <KeyValue label="Near-close snapshots" value={int(o.database.near_close_snapshots)} />
            <KeyValue label="Raw payloads" value={int(o.database.raw_payloads)} />
            <KeyValue label="Predictions" value={int(o.database.predictions)} />
          </Panel>
        </div>
      ) : null}

      {o ? <RunsPanel runs={o.recent_runs} /> : null}

      {o ? (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Picks" subtitle="Shadow picks only; publishing is disabled">
            <SectionView section={o.picks}>
              {(d) => <KeyValue label="Picks" value={int(d?.["picks"] ?? 0)} />}
            </SectionView>
          </Panel>
          <Panel
            title="Performance"
            subtitle="Reported only from settled picks with recorded prices"
          >
            <div className="grid gap-3 sm:grid-cols-2">
              <MetricCard
                label="P&L"
                value={null}
                tone="muted"
                hint="No settled pick with a recorded price"
              />
              <MetricCard
                label="ROI"
                value={null}
                tone="muted"
                hint="Not computable without a settled sample"
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
      title={matches.length ? `In play now · ${matches.length}` : "In play now"}
      subtitle="Tracked matches being played: score and minute from the live follow, refreshed every 15 seconds"
      actions={
        <Link to="/live" className="text-caption text-primary hover:underline">
          Live
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
                    {m.home.name} <span className="text-subtle-foreground">v</span> {m.away.name}
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
          {q.data.reason ?? "No tracked match is in play."}
        </p>
      )}
    </Panel>
  );
}
