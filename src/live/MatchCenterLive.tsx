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
import { t } from "@/lib/i18n";
import { dec, decPct, relative, shortHash, utcDateTime } from "./format";
import { AuditTrail } from "./AuditTrail";
import { HistoricalMarketTables } from "./HistoricalMarket";
import { venueFacts, venuePlace } from "@/product/shared/venue";
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

/** The tab's label in the reader's language; the tab value itself is a fixed id. */
function tabLabel(tab: Tab): string {
  switch (tab) {
    case "Overview":
      return t("center.tabs.overview");
    case "Stats":
      return t("center.tabs.stats");
    case "Events":
      return t("center.tabs.events");
    case "Line-ups":
      return t("center.tabs.lineups");
    case "Players":
      return t("center.tabs.players");
    case "Context":
      return t("center.tabs.context");
    case "Markets":
      return t("center.tabs.markets");
    case "In-play":
      return t("center.tabs.inPlay");
    case "Models":
      return t("center.tabs.models");
    case "Timeline":
      return t("center.tabs.timeline");
    case "Lineage":
      return t("center.tabs.lineage");
    case "Audit":
      return t("center.tabs.audit");
  }
}

export function MatchCenterLive({
  fixtureId,
  hideHeader = false,
}: {
  fixtureId: string;
  /** Embedded under another page's header (the product Match Center's admin tab). */
  hideHeader?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("Overview");
  const q = useLiveQuery(live.match(fixtureId));

  if (q.isLoading) {
    return (
      <div className="space-y-4">
        {hideHeader ? null : (
          <PageHeader title={t("center.header.title")} description={t("center.header.loading")} />
        )}
        <TableSkeleton rows={6} cols={4} />
      </div>
    );
  }
  if (q.isError || !q.data) {
    const notFound = q.error instanceof LiveApiError && q.error.status === 404;
    return (
      <div className="space-y-4">
        {hideHeader ? (
          notFound ? (
            <p className="text-sm text-muted-foreground">
              {t("center.header.noFixture", { id: fixtureId })}
            </p>
          ) : null
        ) : (
          <PageHeader
            breadcrumb={[
              { label: t("center.header.matches"), to: "/matches" },
              { label: t("center.header.fixture", { id: fixtureId }) },
            ]}
            title={notFound ? t("center.header.notFound") : t("center.header.title")}
            description={
              notFound
                ? t("center.header.noFixture", { id: fixtureId })
                : t("center.header.loadFailed")
            }
          />
        )}
        {!notFound ? <ApiErrorNotice error={q.error} /> : null}
      </div>
    );
  }

  const d = q.data.data;
  const m = d.match;
  const sides = { home: m.home.name, away: m.away.name };
  return (
    <div className="space-y-4">
      {hideHeader ? null : (
        <PageHeader
          breadcrumb={[
            { label: t("center.header.matches"), to: "/matches" },
            { label: t("center.versus", { home: m.home.name, away: m.away.name }) },
          ]}
          title={t("center.versus", { home: m.home.name, away: m.away.name })}
          description={`${m.competition.name}${m.round ? ` · ${m.round}` : ""} · ${utcDateTime(m.kickoff_at)}`}
          actions={<StatusGroupBadge match={m} />}
        />
      )}

      {m.awaiting_result ? (
        <WarningBanner>
          {t("center.awaitingResult", { when: relative(m.kickoff_at), status: m.status_short })}
        </WarningBanner>
      ) : null}

      <SegmentedTabs
        label={t("center.tabs.label")}
        tabs={tabs}
        value={tab}
        onChange={setTab}
        format={tabLabel}
      />

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
        <Panel title={t("center.timeline.title")} subtitle={t("center.timeline.subtitle")}>
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
      <Panel title={t("center.overview.result.title")} className="lg:col-span-2">
        <div className="flex flex-col items-center gap-3 py-4 sm:flex-row sm:justify-center sm:gap-8">
          <div className="text-center text-sm font-medium sm:w-48 sm:text-right">{m.home.name}</div>
          <div className="text-3xl">
            {m.score ? (
              <ScoreText score={m.score} />
            ) : (
              <span
                className="numeric text-subtle-foreground"
                title={t("center.overview.result.noScore")}
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
              label={t("center.overview.result.halfTime")}
              value={
                <Nullable
                  value={m.score.ht_home === null ? null : `${m.score.ht_home}–${m.score.ht_away}`}
                  reason={t("center.overview.result.noHalfTime")}
                />
              }
            />
            <KeyValue label={t("center.overview.result.outcome")} value={m.score.outcome_1x2} />
            <KeyValue
              label={t("center.overview.result.extraTime")}
              value={
                <Nullable
                  value={m.score.et_home === null ? null : `${m.score.et_home}–${m.score.et_away}`}
                  reason={t("center.overview.result.noExtraTime")}
                />
              }
            />
            <KeyValue
              label={t("center.overview.result.penalties")}
              value={
                <Nullable
                  value={
                    m.score.pen_home === null ? null : `${m.score.pen_home}–${m.score.pen_away}`
                  }
                  reason={t("center.overview.result.noShootout")}
                />
              }
            />
            <KeyValue
              label={t("center.overview.result.totalGoals")}
              value={int(m.score.total_goals)}
            />
            <KeyValue
              label={t("center.overview.result.btts")}
              value={m.score.btts ? t("center.yes") : t("center.no")}
            />
          </div>
        ) : (
          <p className="text-center text-xs text-muted-foreground">
            {m.status_group === "postponed" || m.status_group === "cancelled"
              ? t("center.overview.result.notPlayed", { status: m.status_short })
              : m.status_group === "live"
                ? t("center.overview.result.inPlay")
                : m.awaiting_result
                  ? t("center.overview.result.awaiting")
                  : t("center.overview.result.scheduled")}
          </p>
        )}
      </Panel>
      <Panel title={t("center.overview.fixture.title")}>
        <KeyValue label={t("center.overview.fixture.kickoff")} value={utcDateTime(m.kickoff_at)} />
        <KeyValue
          label={t("center.overview.fixture.status")}
          value={`${m.status_short} (${m.status_group})`}
        />
        <KeyValue label={t("center.overview.fixture.competition")} value={m.competition.name} />
        <KeyValue label={t("center.overview.fixture.season")} value={m.competition.season} />
        <KeyValue
          label={t("center.overview.fixture.round")}
          value={<Nullable value={m.round} reason={t("center.overview.fixture.noRound")} />}
        />
        <KeyValue
          label={t("center.overview.fixture.venue")}
          value={
            <Nullable
              value={d.venue ? [venuePlace(d.venue), ...venueFacts(d.venue)].join(" · ") : null}
              reason={t("center.overview.fixture.noVenue")}
            />
          }
        />
        <KeyValue label={t("center.overview.fixture.snapshots")} value={int(m.odds.snapshots)} />
        <KeyValue label={t("center.overview.fixture.bookmakers")} value={int(m.odds.bookmakers)} />
        <KeyValue
          label={t("center.overview.fixture.nearClose")}
          value={int(m.odds.near_close_snapshots)}
        />
        <KeyValue label={t("center.overview.fixture.predictions")} value={int(m.predictions)} />
        <div className="mt-3 flex flex-wrap gap-2 text-caption">
          <Link to="/admin/teams" className="text-primary hover:underline">
            {t("center.overview.fixture.teams")}
          </Link>
          <Link to="/admin/odds" className="text-primary hover:underline">
            {t("center.overview.fixture.oddsExplorer")}
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
        title={t("center.markets.captured.title")}
        subtitle={t("center.markets.captured.subtitle")}
        bodyClassName=""
      >
        <SectionView section={d.markets}>
          {(quotes) => (
            <TableShell>
              <THead>
                <TH>{t("center.columns.market")}</TH>
                <TH>{t("center.columns.selection")}</TH>
                <TH>{t("center.columns.bookmaker")}</TH>
                <TH align="right">{t("center.columns.odds")}</TH>
                <TH align="right">{t("center.columns.implied")}</TH>
                <TH>{t("center.columns.captured")}</TH>
                <TH>{t("center.columns.feed")}</TH>
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
        title={t("center.markets.historical.title")}
        subtitle={t("center.markets.historical.subtitle")}
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

/** Column header for a 1X2 selection; the selection itself stays the API's value. */
function selectionLabel(s: (typeof SELECTIONS_1X2)[number]): string {
  switch (s) {
    case "Home":
      return t("center.columns.home");
    case "Draw":
      return t("center.columns.draw");
    case "Away":
      return t("center.columns.away");
  }
}

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
    <Panel title={t("center.models.title")} subtitle={t("center.models.subtitle")} bodyClassName="">
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
                  <StatusBadge tone="warning">{t("center.models.backtest")}</StatusBadge>
                  {t("center.models.backtestNote")}
                </div>
              ) : null}
              <TableShell>
                <THead>
                  <TH>{t("center.columns.model")}</TH>
                  {SELECTIONS_1X2.map((s) => (
                    <TH key={s} align="right" className={outcome === s ? "text-positive" : ""}>
                      {selectionLabel(s)}
                      {outcome === s ? " ✓" : ""}
                    </TH>
                  ))}
                  <TH align="right">{t("center.columns.over25")}</TH>
                  <TH align="right">{t("center.columns.bttsYes")}</TH>
                  <TH>{t("center.columns.dataCutoff")}</TH>
                </THead>
                <tbody>
                  {market ? (
                    <TRow selected>
                      <TD>
                        <div className="text-sm">{t("center.models.market")}</div>
                        <div className="text-caption text-subtle-foreground">
                          {t("center.models.marketNote")}
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
                        <Nullable value={null} reason={t("center.models.only1x2")} />
                      </TD>
                      <TD align="right">
                        <Nullable value={null} reason={t("center.models.noBtts")} />
                      </TD>
                      <TD className="text-caption text-subtle-foreground">
                        {t("center.models.atKickoff")}
                      </TD>
                    </TRow>
                  ) : null}
                  {[...byModel.entries()].map(([key, rs]) => {
                    const first = rs[0]!;
                    return (
                      <TRow key={key}>
                        <TD>
                          <div className="flex items-center gap-2 text-sm">
                            {modelName(first.model)}
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

/** A model's display name; an unknown model shows its key. */
function modelName(model: string): string {
  switch (model) {
    case "poisson":
      return t("center.models.names.poisson");
    case "dixon_coles":
      return t("center.models.names.dixonColes");
    case "elo_ologit":
      return t("center.models.names.eloOlogit");
    case "base_rates":
      return t("center.models.names.baseRates");
    case "mnlogit":
      return t("center.models.names.mnlogit");
    default:
      return model;
  }
}

function ProbCell({ row }: { row: PredictionRow | null }) {
  if (!row) return <Nullable value={null} reason={t("center.models.notPriced")} />;
  return (
    <div className="numeric">
      {decPct(row.p_calibrated)}
      <div className="text-caption text-subtle-foreground">
        {row.p_lo !== null && row.p_hi !== null ? (
          `${decPct(row.p_lo, 0)}–${decPct(row.p_hi, 0)}`
        ) : (
          <Nullable value={null} reason={t("center.models.noInterval")} />
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
      label: t("center.lineage.provider", { provider: l.provider }),
      detail: t("center.lineage.providerDetail", { id: l.provider_fixture_id }),
      reference: t("center.lineage.providerRef", { id: l.provider_fixture_id }),
      at: l.first_seen_at,
    },
    {
      id: "payload",
      label: t("center.lineage.payload"),
      detail: l.recorded
        ? t("center.lineage.payloadDetail", {
            endpoint: l.source_endpoint ?? "?",
            params: l.source_params ? JSON.stringify(l.source_params) : "",
          })
        : (l.note ?? t("center.lineage.notRecorded")),
      reference: l.recorded
        ? `sha256 ${shortHash(l.source_payload_hash)}`
        : t("center.lineage.notLinked"),
      at: l.source_fetched_at,
    },
    {
      id: "run",
      label: t("center.lineage.run"),
      detail: l.source_run_id
        ? t("center.lineage.runDetail", { job: l.source_job_type ?? t("center.lineage.aRun") })
        : t("center.lineage.noRun"),
      reference: l.source_run_id ? t("center.lineage.runRef", { id: l.source_run_id }) : "—",
      at: l.source_fetched_at,
    },
    {
      id: "row",
      label: "core.fixtures",
      detail: t("center.lineage.rowDetail"),
      reference: t("center.lineage.updated", { when: utcDateTime(l.updated_at) }),
      at: l.updated_at,
    },
  ];
  if (s) {
    steps.push({
      id: "score",
      label: "core.fixture_results",
      detail: s.source_payload_hash
        ? t("center.lineage.scoreFromPayload")
        : t("center.lineage.scoreBeforeLineage"),
      reference: s.source_payload_hash
        ? `sha256 ${shortHash(s.source_payload_hash)}`
        : t("center.lineage.notLinked"),
      at: s.source_fetched_at,
    });
  }
  return (
    <Panel title={t("center.lineage.title")} subtitle={t("center.lineage.subtitle")}>
      <AuditTimeline steps={steps} />
    </Panel>
  );
}
