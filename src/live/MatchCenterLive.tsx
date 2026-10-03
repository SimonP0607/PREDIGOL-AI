import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { AuditTimeline, EventTimeline, type AuditStep } from "@/components/system/Timelines";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import type { MatchDetail, PredictionRow } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { dec, decPct, relative, shortHash, utcDateTime } from "./format";
import { AuditTrail } from "./AuditTrail";
import { HistoricalMarketTables } from "./HistoricalMarket";
import { ScoreText, StatusGroupBadge } from "./shared";
import {
  ContextTab,
  EventsTab,
  LineupsTab,
  LiveScoreLine,
  LiveTab,
  PlayersTab,
  StatsTab,
  WithCenter,
} from "./MatchCenterExtra";

const tabs = [
  "Overview",
  "Stats",
  "Events",
  "Line-ups",
  "Players",
  "Context",
  "Markets",
  "In-play",
  "Models",
  "Timeline",
  "Lineage",
  "Audit",
] as const;
type Tab = (typeof tabs)[number];

export function MatchCenterLive({ fixtureId }: { fixtureId: string }) {
  const [tab, setTab] = useState<Tab>("Overview");
  const q = useLiveQuery(live.match(fixtureId));

  if (q.isLoading) {
    return (
      <div className="space-y-4">
        <PageHeader title="Match Center" description="Loading fixture…" />
        <TableSkeleton rows={6} cols={4} />
      </div>
    );
  }
  if (q.isError || !q.data) {
    const notFound = q.error instanceof LiveApiError && q.error.status === 404;
    return (
      <div className="space-y-4">
        <PageHeader
          breadcrumb={[{ label: "Matches", to: "/matches" }, { label: `Fixture ${fixtureId}` }]}
          title={notFound ? "Fixture not found" : "Match Center"}
          description={
            notFound ? `No stored fixture has id ${fixtureId}.` : "The fixture could not be loaded."
          }
        />
        {!notFound ? <ApiErrorNotice error={q.error} /> : null}
      </div>
    );
  }

  const d = q.data.data;
  const m = d.match;
  const sides = { home: m.home.name, away: m.away.name };
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[
          { label: "Matches", to: "/matches" },
          { label: `${m.home.name} v ${m.away.name}` },
        ]}
        title={`${m.home.name} v ${m.away.name}`}
        description={`${m.competition.name}${m.round ? ` · ${m.round}` : ""} · ${utcDateTime(m.kickoff_at)}`}
        actions={<StatusGroupBadge match={m} />}
      />

      {m.awaiting_result ? (
        <WarningBanner>
          This fixture kicked off {relative(m.kickoff_at)} and is still recorded as {m.status_short}
          . The live follower and the results sync should have moved it on; check System / Admin for
          a failing job.
        </WarningBanner>
      ) : null}

      <SegmentedTabs label="Match sections" tabs={tabs} value={tab} onChange={setTab} />

      {tab === "Overview" ? (
        <div className="space-y-4">
          {m.status_group === "live" || m.awaiting_result ? (
            <WithCenter fixtureId={fixtureId}>
              {(c) => <LiveScoreLine c={c} sides={sides} />}
            </WithCenter>
          ) : null}
          <OverviewTab d={d} />
        </div>
      ) : null}
      {tab === "Stats" ? (
        <WithCenter fixtureId={fixtureId}>{(c) => <StatsTab c={c} sides={sides} />}</WithCenter>
      ) : null}
      {tab === "Events" ? (
        <WithCenter fixtureId={fixtureId}>{(c) => <EventsTab c={c} sides={sides} />}</WithCenter>
      ) : null}
      {tab === "Line-ups" ? (
        <WithCenter fixtureId={fixtureId}>{(c) => <LineupsTab c={c} sides={sides} />}</WithCenter>
      ) : null}
      {tab === "Players" ? (
        <WithCenter fixtureId={fixtureId}>{(c) => <PlayersTab c={c} sides={sides} />}</WithCenter>
      ) : null}
      {tab === "Context" ? (
        <WithCenter fixtureId={fixtureId}>{(c) => <ContextTab c={c} sides={sides} />}</WithCenter>
      ) : null}
      {tab === "In-play" ? (
        <WithCenter fixtureId={fixtureId}>{(c) => <LiveTab c={c} />}</WithCenter>
      ) : null}
      {tab === "Markets" ? <MarketsTab d={d} /> : null}
      {tab === "Models" ? <ModelsTab d={d} /> : null}
      {tab === "Timeline" ? (
        <Panel
          title="Timeline"
          subtitle="What the system observed for this fixture, in order. Windows the plan cannot reach are marked, not counted as missed."
        >
          <EventTimeline
            events={d.timeline.map((e) => ({
              id: e.key,
              label: e.label,
              detail: e.detail,
              at: e.at,
              state: e.state,
            }))}
          />
        </Panel>
      ) : null}
      {tab === "Lineage" ? <LineageTab d={d} /> : null}
      {tab === "Audit" ? <AuditTrail fixtureId={fixtureId} /> : null}
    </div>
  );
}

function OverviewTab({ d }: { d: MatchDetail }) {
  const m = d.match;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Panel title="Result" className="lg:col-span-2">
        <div className="flex flex-col items-center gap-3 py-4 sm:flex-row sm:justify-center sm:gap-8">
          <div className="text-center text-sm font-medium sm:w-48 sm:text-right">{m.home.name}</div>
          <div className="text-3xl">
            {m.score ? (
              <ScoreText score={m.score} />
            ) : (
              <span
                className="numeric text-subtle-foreground"
                title="No score has been recorded for this fixture."
              >
                – : –
              </span>
            )}
          </div>
          <div className="text-center text-sm font-medium sm:w-48 sm:text-left">{m.away.name}</div>
        </div>
        {m.score ? (
          <div className="grid gap-x-6 sm:grid-cols-2">
            <KeyValue
              label="Half time"
              value={
                <Nullable
                  value={m.score.ht_home === null ? null : `${m.score.ht_home}–${m.score.ht_away}`}
                  reason="Half-time score not provided."
                />
              }
            />
            <KeyValue label="Outcome (90 min)" value={m.score.outcome_1x2} />
            <KeyValue
              label="Extra time"
              value={
                <Nullable
                  value={m.score.et_home === null ? null : `${m.score.et_home}–${m.score.et_away}`}
                  reason="No extra time was played."
                />
              }
            />
            <KeyValue
              label="Penalties"
              value={
                <Nullable
                  value={
                    m.score.pen_home === null ? null : `${m.score.pen_home}–${m.score.pen_away}`
                  }
                  reason="No shoot-out."
                />
              }
            />
            <KeyValue label="Total goals" value={int(m.score.total_goals)} />
            <KeyValue label="Both teams scored" value={m.score.btts ? "yes" : "no"} />
          </div>
        ) : (
          <p className="text-center text-xs text-muted-foreground">
            {m.status_group === "postponed" || m.status_group === "cancelled"
              ? `Not played (${m.status_short}): there is no result to record.`
              : m.status_group === "live"
                ? "In play: the live score is shown above and in the In-play tab. The result is recorded at full time."
                : m.awaiting_result
                  ? "Kicked off, but no result has been recorded yet."
                  : "Scheduled. The result is recorded after full time."}
          </p>
        )}
      </Panel>
      <Panel title="Fixture">
        <KeyValue label="Kick-off" value={utcDateTime(m.kickoff_at)} />
        <KeyValue label="Status" value={`${m.status_short} (${m.status_group})`} />
        <KeyValue label="Competition" value={m.competition.name} />
        <KeyValue label="Season" value={m.competition.season} />
        <KeyValue
          label="Round"
          value={<Nullable value={m.round} reason="The provider did not report a round." />}
        />
        <KeyValue
          label="Venue"
          value={
            <Nullable
              value={d.venue ? `${d.venue.name}${d.venue.city ? `, ${d.venue.city}` : ""}` : null}
              reason="The provider did not identify the venue."
            />
          }
        />
        <KeyValue label="Odds snapshots" value={int(m.odds.snapshots)} />
        <KeyValue label="Bookmakers" value={int(m.odds.bookmakers)} />
        <KeyValue label="Near-close captures" value={int(m.odds.near_close_snapshots)} />
        <KeyValue label="Predictions" value={int(m.predictions)} />
        <div className="mt-3 flex flex-wrap gap-2 text-caption">
          <Link to="/teams" className="text-primary hover:underline">
            Teams
          </Link>
          <Link to="/odds" className="text-primary hover:underline">
            Odds explorer
          </Link>
        </div>
      </Panel>
    </div>
  );
}

function MarketsTab({ d }: { d: MatchDetail }) {
  const odds = useLiveQuery(live.fixtureOdds(String(d.match.id)));
  return (
    <div className="space-y-4">
      <Panel
        title="Captured prices"
        subtitle="Latest price per bookmaker that THIS platform captured. Implied probability is 1/odds: the bookmaker margin is still in it."
        bodyClassName=""
      >
        <SectionView section={d.markets}>
          {(quotes) => (
            <TableShell>
              <THead>
                <TH>Market</TH>
                <TH>Selection</TH>
                <TH>Bookmaker</TH>
                <TH align="right">Odds</TH>
                <TH align="right">Implied (raw)</TH>
                <TH>Captured</TH>
                <TH>Feed</TH>
              </THead>
              <tbody>
                {quotes.map((qt) => (
                  <TRow key={`${qt.bookmaker_id}-${qt.market_key}-${qt.selection}-${qt.line}`}>
                    <TD className="text-xs">
                      {qt.market_key}
                      {Number(qt.line) !== 0 ? ` ${dec(qt.line, 2)}` : ""}
                    </TD>
                    <TD className="text-sm">{qt.selection}</TD>
                    <TD className="text-xs text-muted-foreground">{qt.bookmaker}</TD>
                    <TD align="right">
                      <Numeric>{dec(qt.odds_decimal, 2)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted>{decPct(qt.implied_probability)}</Numeric>
                    </TD>
                    <TD>
                      <span className="numeric text-xs">T-{qt.minutes_to_ko} min</span>
                      <div className="text-caption text-subtle-foreground">
                        {utcDateTime(qt.captured_at)}
                      </div>
                    </TD>
                    <TD>
                      <StatusBadge tone={qt.source === "live" ? "brand" : "neutral"}>
                        {qt.source}
                      </StatusBadge>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </SectionView>
      </Panel>
      <Panel
        title="Historical market"
        subtitle="Published by a second source after the fact. Kept apart from our captures, never mixed into them."
        bodyClassName="pb-2"
      >
        {odds.isLoading ? (
          <TableSkeleton rows={4} cols={7} />
        ) : odds.isError ? (
          <div className="p-4">
            <ApiErrorNotice error={odds.error} />
          </div>
        ) : odds.data ? (
          <SectionView section={odds.data.data.historical}>
            {(h) => (h ? <HistoricalMarketTables market={h} /> : null)}
          </SectionView>
        ) : null}
      </Panel>
    </div>
  );
}

const SELECTIONS_1X2 = ["Home", "Draw", "Away"] as const;

function ModelsTab({ d }: { d: MatchDetail }) {
  const odds = useLiveQuery(live.fixtureOdds(String(d.match.id)));
  const outcome = d.match.score?.outcome_1x2 ?? null;
  const market =
    odds.data?.data.historical.status === "ok"
      ? (odds.data.data.historical.data?.fair_1x2.find(
          (f) =>
            f.bookmaker_code === "pinnacle" &&
            f.price_kind === "closing" &&
            f.devig_method === "shin",
        ) ?? null)
      : null;
  return (
    <Panel
      title="Model predictions"
      subtitle="Probabilities with their data cut-off. Probability is not confidence; the interval is the model's own parameter uncertainty (90%, Laplace)."
      bodyClassName=""
    >
      <SectionView section={d.predictions}>
        {(rows) => {
          const byModel = new Map<string, PredictionRow[]>();
          for (const r of rows) {
            const key = `${r.kind}|${r.model}|${r.model_version}`;
            byModel.set(key, [...(byModel.get(key) ?? []), r]);
          }
          const find = (rs: PredictionRow[], mk: string, sel: string) =>
            rs.find((r) => r.market_key === mk && r.selection === sel) ?? null;
          const backtest = rows.some((r) => r.kind === "backtest");
          return (
            <div>
              {backtest ? (
                <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2.5 text-caption text-muted-foreground">
                  <StatusBadge tone="warning">Backtest replay</StatusBadge>
                  These were produced by the walk-forward backtest, using only results public before
                  each cut-off. They are not forecasts that were published before the match.
                </div>
              ) : null}
              <TableShell>
                <THead>
                  <TH>Model</TH>
                  {SELECTIONS_1X2.map((s) => (
                    <TH key={s} align="right" className={outcome === s ? "text-positive" : ""}>
                      {s}
                      {outcome === s ? " ✓" : ""}
                    </TH>
                  ))}
                  <TH align="right">Over 2.5</TH>
                  <TH align="right">BTTS yes</TH>
                  <TH>Data cut-off</TH>
                </THead>
                <tbody>
                  {market ? (
                    <TRow selected>
                      <TD>
                        <div className="text-sm">Market · Pinnacle closing · Shin</div>
                        <div className="text-caption text-subtle-foreground">
                          de-vigged, second source
                        </div>
                      </TD>
                      <TD align="right">
                        <Numeric>{decPct(market.p_home)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{decPct(market.p_draw)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric>{decPct(market.p_away)}</Numeric>
                      </TD>
                      <TD align="right">
                        <Nullable value={null} reason="Only the 1X2 baseline is shown here." />
                      </TD>
                      <TD align="right">
                        <Nullable value={null} reason="The source publishes no BTTS prices." />
                      </TD>
                      <TD className="text-caption text-subtle-foreground">at kick-off</TD>
                    </TRow>
                  ) : null}
                  {[...byModel.entries()].map(([key, rs]) => {
                    const first = rs[0]!;
                    return (
                      <TRow key={key}>
                        <TD>
                          <div className="flex items-center gap-2 text-sm">
                            {MODEL_NAMES[first.model] ?? first.model}
                            <StatusBadge tone={first.kind === "backtest" ? "neutral" : "brand"}>
                              {first.kind}
                            </StatusBadge>
                          </div>
                          <div
                            className="numeric text-caption text-subtle-foreground"
                            title={first.model_version}
                          >
                            {first.model_version.split("@")[0]}
                          </div>
                        </TD>
                        {SELECTIONS_1X2.map((s) => (
                          <TD key={s} align="right">
                            <ProbCell row={find(rs, "1X2", s)} />
                          </TD>
                        ))}
                        <TD align="right">
                          <ProbCell row={find(rs, "OU", "Over")} />
                        </TD>
                        <TD align="right">
                          <ProbCell row={find(rs, "BTTS", "Yes")} />
                        </TD>
                        <TD>
                          <Numeric muted>{utcDateTime(first.data_cutoff_ts)}</Numeric>
                        </TD>
                      </TRow>
                    );
                  })}
                </tbody>
              </TableShell>
            </div>
          );
        }}
      </SectionView>
    </Panel>
  );
}

const MODEL_NAMES: Record<string, string> = {
  poisson: "Poisson",
  dixon_coles: "Dixon-Coles",
  elo_ologit: "Elo + ordered logit",
  base_rates: "League base rates",
  mnlogit: "Multinomial logit",
};

function ProbCell({ row }: { row: PredictionRow | null }) {
  if (!row) return <Nullable value={null} reason="This model does not price this market." />;
  return (
    <div className="numeric">
      {decPct(row.p_calibrated)}
      <div className="text-caption text-subtle-foreground">
        {row.p_lo !== null && row.p_hi !== null ? (
          `${decPct(row.p_lo, 0)}–${decPct(row.p_hi, 0)}`
        ) : (
          <Nullable value={null} reason="No interval was computed for this prediction." />
        )}
      </div>
    </div>
  );
}

function LineageTab({ d }: { d: MatchDetail }) {
  const l = d.lineage;
  const s = d.match.score;
  const steps: AuditStep[] = [
    {
      id: "provider",
      label: `Provider: ${l.provider}`,
      detail: `Fixture ${l.provider_fixture_id} as the provider identifies it.`,
      reference: `fixture ${l.provider_fixture_id}`,
      at: l.first_seen_at,
    },
    {
      id: "payload",
      label: "Raw payload",
      detail: l.recorded
        ? `${l.source_endpoint ?? "?"} ${l.source_params ? JSON.stringify(l.source_params) : ""}, stored gzipped and indexed by its hash.`
        : (l.note ?? "Not recorded."),
      reference: l.recorded ? `sha256 ${shortHash(l.source_payload_hash)}` : "not linked",
      at: l.source_fetched_at,
    },
    {
      id: "run",
      label: "Ingestion run",
      detail: l.source_run_id
        ? `Written by ${l.source_job_type ?? "a run"}; see the job ledger.`
        : "No run linked to this row.",
      reference: l.source_run_id ? `run ${l.source_run_id}` : "—",
      at: l.source_fetched_at,
    },
    {
      id: "row",
      label: "core.fixtures",
      detail:
        "Normalised row. Writes are monotonic on the payload fetch time: an older payload never overwrites a newer one.",
      reference: `updated ${utcDateTime(l.updated_at)}`,
      at: l.updated_at,
    },
  ];
  if (s) {
    steps.push({
      id: "score",
      label: "core.fixture_results",
      detail: s.source_payload_hash
        ? "The score was read from this payload."
        : "Score written before lineage was recorded (revision 0015).",
      reference: s.source_payload_hash
        ? `sha256 ${shortHash(s.source_payload_hash)}`
        : "not linked",
      at: s.source_fetched_at,
    });
  }
  return (
    <Panel title="Lineage" subtitle="From the provider's bytes to the row on screen">
      <AuditTimeline steps={steps} />
    </Panel>
  );
}
