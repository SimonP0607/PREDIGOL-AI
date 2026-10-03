import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { PageHeader } from "@/components/layout/PageHeader";
import { Panel, MetricCard, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import {
  DataStateBadge,
  ModelBadge,
  StatusBadge,
  PickStatusBadge,
} from "@/components/primitives/StatusBadge";
import {
  CompetitionBadge,
  EdgeIndicator,
  EVIndicator,
  Numeric,
  OddsCell,
  TeamBadge,
} from "@/components/primitives/Indicators";
import { cn } from "@/lib/utils";
import { FreshnessBadge, freshnessFromState } from "@/components/system/Freshness";
import { MetricLabel } from "@/components/system/InfoTip";
import { queries } from "@/lib/api/resources";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { OverviewLive } from "@/live/OverviewLive";
import { EMPTY, dateTimeOf, int, pct, timeOf } from "@/lib/format";
import { models as modelList } from "@/mock/data";

export const Route = createFileRoute("/admin/overview")({
  head: () => ({
    meta: [
      { title: "Overview · PrediGol Admin" },
      {
        name: "description",
        content:
          "Operations overview: monitored fixtures, model versus market candidates, system health and model status.",
      },
      { property: "og:title", content: "Overview · PrediGol Admin" },
      {
        property: "og:description",
        content: "Operations overview for the football intelligence workspace.",
      },
    ],
  }),
  component: OverviewRoute,
});

function OverviewRoute() {
  if (DATA_MODE === "mock") {
    return (
      <DemoRegion>
        <OverviewDemo />
      </DemoRegion>
    );
  }
  return <OverviewLive />;
}

function OverviewDemo() {
  const matches = useQuery(queries.matches);
  const picks = useQuery(queries.picks);
  const health = useQuery(queries.health);
  const performance = useQuery(queries.performance);

  const upcoming = (matches.data ?? []).filter((f) => f.status === "upcoming");
  const opportunities = (picks.data ?? []).filter((p) => p.status !== "rejected");

  return (
    <div className="space-y-5">
      <PageHeader
        title="Overview"
        description="Operations view for today. Every figure below comes from demo data until the engine is connected."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="brand">Shadow mode</StatusBadge>
          </div>
        }
      />

      <dl className="surface-panel grid grid-cols-2 divide-border sm:grid-cols-4 sm:divide-x">
        {[
          { label: "Today", value: "04 Sep 2026", hint: "All timestamps in UTC", tone: "plain" },
          {
            label: "Monitored fixtures",
            value: int(matches.data?.length ?? null),
            hint: `${upcoming.length} upcoming · 6 competitions`,
          },
          { label: "Last synchronisation", value: "12:03 UTC", hint: "Fixtures + odds snapshot" },
          {
            label: "System state",
            value: "Degraded",
            hint: "1 failed job · 3 stale captures",
            tone: "warning",
          },
        ].map((cell) => (
          <div key={cell.label} className="px-4 py-3">
            <dt className="text-label text-subtle-foreground">{cell.label}</dt>
            <dd
              className={cn(
                "numeric mt-1 flex items-center gap-1.5 text-base",
                cell.tone === "warning" ? "text-warning" : "text-foreground",
              )}
            >
              {cell.tone === "warning" ? (
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-warning" />
              ) : null}
              {cell.value}
            </dd>
            <dd className="mt-0.5 text-caption text-muted-foreground">{cell.hint}</dd>
          </div>
        ))}
      </dl>

      <WarningBanner>
        The platform is running in research / shadow mode. No pick has been published, and no
        profitability figure is available or implied.
      </WarningBanner>

      <div className="grid gap-5 xl:grid-cols-3">
        <Panel
          title="Upcoming matches"
          subtitle="Fixtures currently monitored by the ingestion layer"
          className="xl:col-span-2"
          bodyClassName=""
          actions={
            <Link to="/matches" className="text-caption text-primary hover:underline">
              All matches
            </Link>
          }
        >
          {matches.isLoading ? (
            <TableSkeleton rows={6} cols={6} />
          ) : (
            <TableShell className="min-w-0">
              <THead>
                <TH>Time</TH>
                <TH>League</TH>
                <TH>Fixture</TH>
                <TH align="right">Coverage</TH>
                <TH>Model</TH>
                <TH>Odds</TH>
              </THead>
              <tbody>
                {upcoming.map((f) => (
                  <TRow key={f.id}>
                    <TD>
                      <Numeric>{timeOf(f.kickoff)}</Numeric>
                    </TD>
                    <TD>
                      <CompetitionBadge
                        code={f.competition.shortCode}
                        name={f.competition.country}
                      />
                    </TD>
                    <TD>
                      <Link
                        to="/matches/$fixtureId"
                        params={{ fixtureId: f.id }}
                        className="flex items-center gap-2 hover:text-primary"
                      >
                        <TeamBadge code={f.home.code} name={f.home.name} />
                        <span className="text-subtle-foreground">vs</span>
                        <TeamBadge code={f.away.code} name={f.away.name} />
                      </Link>
                    </TD>
                    <TD align="right">
                      <Numeric>{pct(f.marketCoverage, 0)}</Numeric>
                    </TD>
                    <TD>
                      <ModelBadge status={f.modelStatus} />
                    </TD>
                    <TD>
                      <DataStateBadge state={f.oddsState} />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>

        <div className="space-y-5">
          <Panel title="System health" subtitle="Ingestion and infrastructure">
            <ul className="space-y-2.5">
              {(health.data ?? []).map((h) => (
                <li key={h.component} className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm">{h.component}</div>
                    <div className="text-caption text-subtle-foreground">{h.detail}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <Numeric className="text-xs" muted>
                      {h.value}
                    </Numeric>
                    <FreshnessBadge freshness={freshnessFromState(h.state)} detail={h.detail} />
                  </div>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Model health" subtitle="Nothing has reached validated status">
            <ul className="space-y-2.5">
              {modelList.slice(0, 4).map((m) => (
                <li key={m.id} className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm">{m.name}</div>
                    <div className="text-caption text-subtle-foreground">
                      {m.sample ? `${int(m.sample)} scored fixtures` : "No evaluation sample"}
                    </div>
                  </div>
                  <ModelBadge status={m.status} />
                </li>
              ))}
            </ul>
          </Panel>
        </div>
      </div>

      <Panel
        title="Opportunities"
        subtitle="Model vs market candidates. Candidates are research output, not advice."
        bodyClassName=""
        actions={
          <Link to="/admin/picks" className="text-caption text-primary hover:underline">
            Picks center
          </Link>
        }
      >
        {picks.isLoading ? (
          <TableSkeleton rows={5} cols={9} />
        ) : (
          <TableShell className="min-w-full">
            <THead>
              <TH>Fixture</TH>
              <TH>Market</TH>
              <TH>Selection</TH>
              <TH align="right">
                <MetricLabel term="modelProbability">Model prob</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="marketProbability">Market prob</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="fairOdds">Fair odds</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="bestOdds">Best odds</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="edge">Edge</MetricLabel>
              </TH>
              <TH align="right">
                <MetricLabel term="ev">EV</MetricLabel>
              </TH>
              <TH>Status</TH>
            </THead>
            <tbody>
              {opportunities.map((p) => (
                <TRow key={p.id}>
                  <TD>
                    <Link
                      to="/matches/$fixtureId"
                      params={{ fixtureId: p.fixtureId }}
                      className="hover:text-primary"
                    >
                      <div className="truncate text-sm">{p.fixtureLabel}</div>
                      <div className="text-caption text-subtle-foreground">{p.competition}</div>
                    </Link>
                  </TD>
                  <TD className="text-xs text-muted-foreground">{p.marketLabel}</TD>
                  <TD className="text-sm">{p.selection}</TD>
                  <TD align="right">
                    <Numeric>{pct(p.modelProbability)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric muted>{pct(p.marketProbability)}</Numeric>
                  </TD>
                  <TD align="right">
                    <OddsCell value={p.fairOdds} fair />
                  </TD>
                  <TD align="right">
                    <OddsCell value={p.bestOdds} bookmaker={p.bookmaker} />
                  </TD>
                  <TD align="right">
                    <EdgeIndicator value={p.edge} />
                  </TD>
                  <TD align="right">
                    <EVIndicator value={p.ev} />
                  </TD>
                  <TD>
                    <PickStatusBadge status={p.status} />
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>

      <Panel
        title="Performance"
        subtitle="Reported only from published, settled picks"
        actions={<StatusBadge tone="neutral">Insufficient sample</StatusBadge>}
      >
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="P&L" value={EMPTY} tone="muted" hint="No settled picks" />
          <MetricCard label="ROI" value={EMPTY} tone="muted" hint="Not computable" />
          <MetricCard
            label="Pick line value"
            value={EMPTY}
            tone="muted"
            hint="Near-close capture pending validation"
          />
          <MetricCard
            label="Published picks"
            value={int(performance.data?.publishedPicks ?? 0)}
            tone="muted"
            hint="Shadow mode only"
          />
        </div>
        <p className="mt-3 text-xs text-muted-foreground">
          {performance.data?.note ?? "Insufficient sample to conclude anything."} Last engine
          evaluation: <span className="numeric">{dateTimeOf("2026-09-03T22:10:00Z")}</span>.
        </p>
      </Panel>
    </div>
  );
}
