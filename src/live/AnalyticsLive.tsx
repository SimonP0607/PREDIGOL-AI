/**
 * Analytics, live: exploratory views over what is stored - competitions,
 * teams, the market, the research registry, data coverage and the historical
 * migration. Every figure is a count or a mean over stored rows, computed by
 * the API at request time; a small sample is shown with its n and flagged.
 */
import { t } from "@/lib/i18n";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { CalibrationChart, ChartContainer } from "@/components/analytics/Charts";
import { sized, type ChartSize } from "@/components/analytics/chartSize";
import { SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { Envelope, ExperimentSummary, TeamAnalytics } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { ratio, shortHash, utcDate, utcDateTime } from "./format";

const tabs = ["Competitions", "Teams", "Models", "Market", "Coverage", "Migration"] as const;
type Tab = (typeof tabs)[number];

/** A tab's name in the reader's language; the value itself stays the English id. */
function tabLabel(tab: Tab): string {
  switch (tab) {
    case "Competitions":
      return t("analytics.tabs.competitions");
    case "Teams":
      return t("analytics.tabs.teams");
    case "Models":
      return t("analytics.tabs.models");
    case "Market":
      return t("analytics.tabs.market");
    case "Coverage":
      return t("analytics.tabs.coverage");
    case "Migration":
      return t("analytics.tabs.migration");
  }
}

const STATUS_TONE: Record<ExperimentSummary["research_status"], BadgeTone> = {
  RESEARCH: "neutral",
  CANDIDATE: "info",
  PRODUCTION: "positive",
  RETIRED: "neutral",
};

function num(v: number | null | undefined, digits = 2): string | null {
  return v === null || v === undefined || !Number.isFinite(v) ? null : v.toFixed(digits);
}

function signed(v: number | null | undefined, digits = 4): string | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}`;
}

function Cell({ value, reason }: { value: string | null; reason?: string }) {
  return value === null ? (
    <span className="text-subtle-foreground" title={reason ?? t("analytics.common.noValue")}>
      —
    </span>
  ) : (
    <Numeric>{value}</Numeric>
  );
}

function Loading<T>({
  q,
  children,
}: {
  q: { isLoading: boolean; isError: boolean; error: unknown; data: Envelope<T> | undefined };
  children: (data: T) => React.ReactNode;
}) {
  if (q.isLoading) return <TableSkeleton rows={8} cols={6} />;
  if (q.isError || !q.data) return <ApiErrorNotice error={q.error} />;
  if (q.data.status !== "ok") return <StatusNotice status={q.data.status} reason={q.data.reason} />;
  return <>{children(q.data.data)}</>;
}

export function AnalyticsLive() {
  const [tab, setTab] = useState<Tab>("Competitions");
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.analytics.title")}
        description={t("admin.pages.analytics.description")}
      />
      <SegmentedTabs
        label={t("analytics.tabs.label")}
        tabs={tabs}
        value={tab}
        onChange={setTab}
        format={tabLabel}
      />
      {tab === "Competitions" ? <CompetitionsTab /> : null}
      {tab === "Teams" ? <TeamsTab /> : null}
      {tab === "Models" ? <ModelsTab /> : null}
      {tab === "Market" ? <MarketTab /> : null}
      {tab === "Coverage" ? <CoverageTab /> : null}
      {tab === "Migration" ? <MigrationTab /> : null}
    </div>
  );
}

function CompetitionsTab() {
  const q = useLiveQuery(live.competitionProfiles);
  return (
    <Panel
      title={t("analytics.competitions.title")}
      subtitle={t("analytics.competitions.subtitle")}
      bodyClassName=""
    >
      <Loading q={q}>
        {(rows) => (
          <TableShell>
            <THead>
              <TH>{t("analytics.common.competition")}</TH>
              <TH align="right">{t("analytics.common.season")}</TH>
              <TH align="right">{t("analytics.competitions.results")}</TH>
              <TH align="right">{t("analytics.common.home")}</TH>
              <TH align="right">{t("analytics.common.draw")}</TH>
              <TH align="right">{t("analytics.common.away")}</TH>
              <TH align="right">{t("analytics.competitions.goals")}</TH>
              <TH align="right">{t("analytics.competitions.homeEdge")}</TH>
              <TH align="right">BTTS</TH>
              <TH align="right">{t("analytics.competitions.over25")}</TH>
              <TH align="right">{t("analytics.competitions.stats")}</TH>
              <TH align="right">{t("analytics.competitions.odds")}</TH>
              <TH align="right">{t("analytics.common.features")}</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={`${r.competition_id}-${r.season}`}>
                  <TD>
                    <div className="flex items-center gap-2 text-sm">
                      {r.competition}
                      {r.low_sample ? (
                        <StatusBadge tone="warning">
                          {t("analytics.competitions.smallSample")}
                        </StatusBadge>
                      ) : null}
                    </div>
                    <div className="text-caption text-subtle-foreground">
                      {r.country ?? t("analytics.competitions.international")}
                    </div>
                  </TD>
                  <TD align="right">
                    <Numeric muted>{r.season}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(r.finished)}</Numeric>
                    <div className="text-caption text-subtle-foreground">
                      {t("analytics.competitions.ofFixtures", { n: int(r.fixtures) })}
                    </div>
                  </TD>
                  <TD align="right">
                    <Cell value={ratio(r.home_win)} />
                  </TD>
                  <TD align="right">
                    <Cell value={ratio(r.draw)} />
                  </TD>
                  <TD align="right">
                    <Cell value={ratio(r.away_win)} />
                  </TD>
                  <TD align="right">
                    <Cell value={num(r.goals_per_match)} />
                  </TD>
                  <TD align="right">
                    <Cell value={signed(r.home_goal_difference, 2)} />
                  </TD>
                  <TD align="right">
                    <Cell value={ratio(r.btts)} />
                  </TD>
                  <TD align="right">
                    <Cell value={ratio(r.over_2_5)} />
                  </TD>
                  <TD align="right">
                    <Numeric muted>{int(r.with_team_stats)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric muted>{int(r.with_historical_odds + r.with_odds_snapshots)}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric muted>{int(r.with_features)}</Numeric>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Loading>
    </Panel>
  );
}

function EloChart({ points, width, height }: { points: TeamAnalytics["elo"] } & ChartSize) {
  const data = points.map((p) => ({
    at: utcDate(p.kickoff_at),
    rating: Math.round(p.rating_after),
  }));
  return (
    <LineChart
      {...sized({ width, height })}
      data={data}
      margin={{ top: 6, right: 12, bottom: 0, left: -12 }}
    >
      <CartesianGrid stroke="var(--color-border)" strokeDasharray="2 4" vertical={false} />
      <XAxis
        dataKey="at"
        stroke="var(--color-border-strong)"
        tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
        tickLine={false}
        minTickGap={40}
      />
      <YAxis
        domain={["dataMin - 20", "dataMax + 20"]}
        stroke="var(--color-border-strong)"
        tick={{ fill: "var(--color-subtle-foreground)", fontSize: 10 }}
        tickLine={false}
        width={52}
      />
      <Tooltip
        contentStyle={{
          background: "var(--color-card)",
          border: "1px solid var(--color-border-strong)",
          borderRadius: 6,
          fontSize: 11,
        }}
      />
      <Line
        type="monotone"
        dataKey="rating"
        name={t("analytics.teams.elo.rating")}
        stroke="var(--color-primary)"
        strokeWidth={1.6}
        dot={false}
        isAnimationActive={false}
      />
    </LineChart>
  );
}

const FEATURE_DIGITS: Record<string, number> = {
  elo: 0,
  history_n: 0,
  rest_days: 1,
  ppg5: 2,
};

/** A feature shown in the team view, in the reader's language; null for one it leaves out. */
function featureLabel(key: string): string | null {
  switch (key) {
    case "elo":
      return t("analytics.teams.features.labels.elo");
    case "pi":
      return t("analytics.teams.features.labels.pi");
    case "shot_share10":
      return t("analytics.teams.features.labels.shotShare10");
    case "sot_share10":
      return t("analytics.teams.features.labels.sotShare10");
    case "elo_resid10":
      return t("analytics.teams.features.labels.eloResid10");
    case "ppg5":
      return t("analytics.teams.features.labels.ppg5");
    case "rest_days":
      return t("analytics.teams.features.labels.restDays");
    case "history_n":
      return t("analytics.teams.features.labels.historyN");
    default:
      return null;
  }
}

/** The side a feature set was built for ("home" / "away" from the API), for display. */
function sideLabel(side: string): string {
  if (side === "home") return t("analytics.teams.features.home");
  if (side === "away") return t("analytics.teams.features.away");
  return side;
}

function TeamsTab() {
  const teams = useLiveQuery(live.teams);
  const options = (teams.data?.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));
  const [teamId, setTeamId] = useState("");
  const chosen = teamId || (options[0] ? String(options[0].id) : "");
  const q = useLiveQuery(live.teamAnalytics(chosen));
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="team-select" className="text-label text-subtle-foreground">
          {t("analytics.teams.team")}
        </label>
        <select
          id="team-select"
          value={chosen}
          onChange={(e) => setTeamId(e.target.value)}
          className="h-8 rounded-md border border-border bg-card px-2 text-sm"
        >
          {options.map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </select>
      </div>
      {!chosen ? (
        <StatusNotice status="empty" reason={t("analytics.teams.noTeam")} />
      ) : q.isLoading ? (
        <TableSkeleton rows={6} cols={4} />
      ) : q.isError || !q.data ? (
        <ApiErrorNotice error={q.error} />
      ) : (
        <TeamView d={q.data.data} status={q.data.status} reason={q.data.reason} />
      )}
    </div>
  );
}

function TeamView({
  d,
  status,
  reason,
}: {
  d: TeamAnalytics;
  status: string;
  reason: string | null;
}) {
  const last = d.process.slice(-10).reverse();
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Panel
        title={t("analytics.teams.record.title", { team: d.team.name })}
        subtitle={t("analytics.teams.record.subtitle")}
        bodyClassName=""
      >
        {status !== "ok" ? (
          <StatusNotice status="insufficient_data" reason={reason} compact />
        ) : (
          <TableShell>
            <THead>
              <TH>{t("analytics.teams.record.split")}</TH>
              <TH align="right">{t("analytics.teams.record.played")}</TH>
              <TH align="right">{t("analytics.teams.record.won")}</TH>
              <TH align="right">{t("analytics.teams.record.drawn")}</TH>
              <TH align="right">{t("analytics.teams.record.lost")}</TH>
              <TH align="right">{t("analytics.teams.record.goalsFor")}</TH>
              <TH align="right">{t("analytics.teams.record.goalsAgainst")}</TH>
              <TH align="right" title={t("analytics.teams.record.ppmTitle")}>
                {t("analytics.teams.record.ppm")}
              </TH>
            </THead>
            <tbody>
              {(["all", "home", "away"] as const).map((k) => {
                const s = d.splits[k];
                return (
                  <TRow key={k}>
                    <TD>
                      {k === "all"
                        ? t("analytics.teams.record.all")
                        : k === "home"
                          ? t("analytics.common.home")
                          : t("analytics.common.away")}
                    </TD>
                    <TD align="right">
                      <Numeric>{int(s.played)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(s.won)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(s.drawn)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(s.lost)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(s.goals_for)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{int(s.goals_against)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Cell
                        value={num(s.points_per_match)}
                        reason={t("analytics.teams.record.noMatch")}
                      />
                    </TD>
                  </TRow>
                );
              })}
            </tbody>
          </TableShell>
        )}
      </Panel>
      {d.elo.length ? (
        <ChartContainer
          title={t("analytics.teams.elo.title")}
          subtitle={t("analytics.teams.elo.subtitle", {
            count: d.elo.length,
            from: utcDate(d.elo[0]?.kickoff_at),
            to: utcDate(d.elo[d.elo.length - 1]?.kickoff_at),
          })}
        >
          <EloChart points={d.elo} />
        </ChartContainer>
      ) : (
        <Panel title="Elo">
          <StatusNotice status="empty" reason={t("analytics.teams.elo.none")} compact />
        </Panel>
      )}
      <Panel
        title={t("analytics.teams.features.title")}
        subtitle={
          d.features
            ? t("analytics.teams.features.subtitle", {
                version: d.features.feature_version,
                fixture: d.features.fixture_id,
                cutoff: utcDateTime(d.features.data_cutoff),
                side: sideLabel(d.features.side),
              })
            : t("analytics.teams.features.newest")
        }
      >
        {d.features ? (
          <div className="grid gap-x-8 sm:grid-cols-2">
            {Object.entries(d.features.values)
              .filter(([k]) => featureLabel(k) !== null)
              .map(([k, v]) => (
                <KeyValue
                  key={k}
                  label={featureLabel(k) ?? k}
                  value={
                    <Cell
                      value={num(v, FEATURE_DIGITS[k] ?? 3)}
                      reason={t("analytics.teams.features.notEnough")}
                    />
                  }
                />
              ))}
          </div>
        ) : (
          <StatusNotice status="empty" reason={t("analytics.teams.features.none")} compact />
        )}
      </Panel>
      <Panel
        title={t("analytics.teams.shots.title")}
        subtitle={t("analytics.teams.shots.subtitle")}
        bodyClassName=""
      >
        {last.length ? (
          <TableShell>
            <THead>
              <TH>{t("analytics.teams.shots.match")}</TH>
              <TH align="right">{t("analytics.teams.shots.shots")}</TH>
              <TH align="right">{t("analytics.teams.shots.onTarget")}</TH>
              <TH>{t("analytics.teams.shots.source")}</TH>
            </THead>
            <tbody>
              {last.map((p) => (
                <TRow key={p.fixture_id}>
                  <TD>
                    <span className="numeric text-xs">{utcDate(p.kickoff_at)}</span>
                  </TD>
                  <TD align="right">
                    <Numeric>
                      {p.shots_for ?? "—"} – {p.shots_against ?? "—"}
                    </Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>
                      {p.shots_on_target_for ?? "—"} – {p.shots_on_target_against ?? "—"}
                    </Numeric>
                  </TD>
                  <TD>
                    <span className="text-caption text-muted-foreground">{p.source}</span>
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        ) : (
          <StatusNotice
            status="empty"
            reason={t("analytics.teams.shots.none")}
            compact
            className="px-4"
          />
        )}
      </Panel>
    </div>
  );
}

function ModelsTab() {
  const q = useLiveQuery(live.experiments);
  return (
    <Panel
      title={t("analytics.models.title")}
      subtitle={t("analytics.models.subtitle")}
      bodyClassName=""
    >
      <Loading q={q}>
        {(all) => {
          const rows = all.filter((e) => e.reproduction_of === null);
          const reruns = all.length - rows.length;
          return (
            <>
              <TableShell>
                <THead>
                  <TH>{t("analytics.models.experiment")}</TH>
                  <TH>{t("analytics.common.status")}</TH>
                  <TH align="right">Log loss</TH>
                  <TH align="right">{t("analytics.models.vsMarket")}</TH>
                  <TH>{t("analytics.models.verdict")}</TH>
                  <TH>{t("analytics.models.gate")}</TH>
                </THead>
                <tbody>
                  {rows.map((e) => (
                    <TRow key={e.id}>
                      <TD>
                        <div className="text-sm">{e.model_family}</div>
                        <div className="numeric text-caption text-subtle-foreground">
                          #{e.id} ·{" "}
                          {t("analytics.models.session", { id: e.backtest_session_id ?? "—" })} ·{" "}
                          {shortHash(e.code_version, 7)}
                          {e.reproduction_of
                            ? ` · ${t("analytics.models.reproduces", { id: e.reproduction_of })}`
                            : ""}
                        </div>
                      </TD>
                      <TD>
                        <StatusBadge tone={STATUS_TONE[e.research_status]}>
                          {e.research_status}
                        </StatusBadge>
                        {e.reproduced_by !== null ? (
                          <div className="mt-1 text-caption text-positive">
                            {t("analytics.models.reproducedBy", { id: e.reproduced_by })}
                          </div>
                        ) : null}
                      </TD>
                      <TD align="right">
                        <Cell value={num(e.own_logloss, 4)} />
                        <div className="text-caption text-subtle-foreground">n {int(e.own_n)}</div>
                      </TD>
                      <TD align="right">
                        <Cell value={signed(e.market_logloss_diff)} />
                        <div className="numeric text-caption text-subtle-foreground">
                          [{signed(e.market_diff_low) ?? "—"}, {signed(e.market_diff_high) ?? "—"}]
                        </div>
                      </TD>
                      <TD>
                        <span className="text-xs">{e.verdict ?? "—"}</span>
                        <div className="text-caption text-subtle-foreground">
                          {t("analytics.models.evidence", { value: e.evidence ?? "—" })}
                        </div>
                      </TD>
                      <TD>
                        <ul className="space-y-0.5">
                          {e.gate.map((g) => (
                            <li
                              key={g.name}
                              title={g.evidence}
                              className={
                                g.passed
                                  ? "text-caption text-positive"
                                  : "text-caption text-negative"
                              }
                            >
                              {g.passed ? "✓" : "✗"} {g.name.replaceAll("_", " ")}
                            </li>
                          ))}
                        </ul>
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
              {reruns ? (
                <p className="px-4 py-2 text-caption text-muted-foreground">
                  {t("analytics.models.reruns", { count: reruns })}
                </p>
              ) : null}
            </>
          );
        }}
      </Loading>
    </Panel>
  );
}

function MarketTab() {
  const q = useLiveQuery(live.marketAnalytics);
  return (
    <Loading q={q}>
      {(m) => (
        <div className="grid gap-4 xl:grid-cols-2">
          <ChartContainer
            title={t("analytics.market.calibration.title")}
            subtitle={t("analytics.market.calibration.subtitle", {
              baseline: m.baseline,
              n: int(m.n_fixtures),
            })}
            height={260}
          >
            <CalibrationChart
              bins={m.calibration
                .filter((b) => b.n > 0 && b.mean_probability !== null && b.observed_rate !== null)
                .map((b) => ({
                  predicted: b.mean_probability ?? 0,
                  observed: b.observed_rate ?? 0,
                  sample: b.n,
                }))}
            />
          </ChartContainer>
          <Panel title={t("analytics.market.buckets.title")} subtitle={m.source} bodyClassName="">
            <TableShell>
              <THead>
                <TH>{t("analytics.market.buckets.bucket")}</TH>
                <TH align="right">n</TH>
                <TH align="right">{t("analytics.market.buckets.meanStated")}</TH>
                <TH align="right">{t("analytics.market.buckets.observed")}</TH>
              </THead>
              <tbody>
                {m.calibration.map((b) => (
                  <TRow key={b.lower}>
                    <TD>
                      <span className="numeric text-xs">
                        {(b.lower * 100).toFixed(0)}–{(b.upper * 100).toFixed(0)}%
                      </span>
                    </TD>
                    <TD align="right">
                      <Numeric muted>{int(b.n)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Cell
                        value={ratio(b.mean_probability, 1)}
                        reason={t("analytics.market.buckets.empty")}
                      />
                    </TD>
                    <TD align="right">
                      <Cell
                        value={ratio(b.observed_rate, 1)}
                        reason={t("analytics.market.buckets.empty")}
                      />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Panel>
          <Panel
            title={t("analytics.market.closing.title")}
            subtitle={t("analytics.market.closing.subtitle")}
            bodyClassName=""
            className="xl:col-span-2"
          >
            <TableShell>
              <THead>
                <TH>{t("analytics.common.competition")}</TH>
                <TH align="right">{t("analytics.common.season")}</TH>
                <TH align="right">n</TH>
                <TH align="right">{t("analytics.market.closing.preClosing")}</TH>
                <TH align="right">{t("analytics.market.closing.closing")}</TH>
                <TH align="right">{t("analytics.market.closing.improvement")}</TH>
                <TH align="right">{t("analytics.market.closing.margin")}</TH>
              </THead>
              <tbody>
                {m.by_season.map((s) => (
                  <TRow key={`${s.competition_id}-${s.season}`}>
                    <TD>{s.competition}</TD>
                    <TD align="right">
                      <Numeric muted>{s.season}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted>{int(s.n)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Cell value={num(s.pre_closing_logloss, 4)} />
                    </TD>
                    <TD align="right">
                      <Cell value={num(s.closing_logloss, 4)} />
                    </TD>
                    <TD align="right">
                      <Cell value={signed(s.closing_improvement)} />
                    </TD>
                    <TD align="right">
                      <Cell
                        value={
                          s.mean_overround_closing === null
                            ? null
                            : `${((s.mean_overround_closing - 1) * 100).toFixed(2)}%`
                        }
                        reason={t("analytics.market.closing.noPrices")}
                      />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Panel>
        </div>
      )}
    </Loading>
  );
}

function CoverageTab() {
  const q = useLiveQuery(live.dataCoverage);
  const cols = [
    ["with_result", t("analytics.coverage.results")],
    ["with_team_stats", t("analytics.coverage.teamStats")],
    ["with_events", t("analytics.coverage.events")],
    ["with_lineups", t("analytics.coverage.lineups")],
    ["with_player_stats", t("analytics.coverage.players")],
    ["with_historical_odds", t("analytics.coverage.histOdds")],
    ["with_odds_snapshots", t("analytics.common.snapshots")],
    ["with_features", t("analytics.common.features")],
    ["with_predictions", t("analytics.coverage.predictions")],
  ] as const;
  return (
    <Panel
      title={t("analytics.coverage.title")}
      subtitle={t("analytics.coverage.subtitle")}
      bodyClassName=""
    >
      <Loading q={q}>
        {(rows) => (
          <TableShell>
            <THead>
              <TH>{t("analytics.common.competition")}</TH>
              <TH align="right">{t("analytics.common.season")}</TH>
              <TH align="right">{t("analytics.common.fixtures")}</TH>
              {cols.map(([k, label]) => (
                <TH key={k} align="right">
                  {label}
                </TH>
              ))}
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={`${r.competition_id}-${r.season}`}>
                  <TD>{r.competition}</TD>
                  <TD align="right">
                    <Numeric muted>{r.season}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(r.fixtures)}</Numeric>
                  </TD>
                  {cols.map(([k]) => {
                    const v = r[k];
                    const share = r.fixtures ? v / r.fixtures : 0;
                    return (
                      <TD key={k} align="right">
                        <span
                          className={
                            v === 0
                              ? "numeric text-subtle-foreground"
                              : share >= 0.95
                                ? "numeric text-positive"
                                : "numeric"
                          }
                        >
                          {int(v)}
                        </span>
                      </TD>
                    );
                  })}
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Loading>
    </Panel>
  );
}

export function MigrationTab() {
  const q = useLiveQuery(live.migration);
  return (
    <Loading q={q}>
      {(m) => (
        <div className="grid gap-4 xl:grid-cols-2">
          <Panel
            title={t("analytics.migration.plan.title")}
            subtitle={t("analytics.migration.plan.subtitle")}
          >
            <KeyValue
              label={t("analytics.migration.plan.name")}
              value={m.plan_name ?? t("analytics.migration.plan.none")}
            />
            <KeyValue
              label={t("analytics.migration.plan.created")}
              value={utcDateTime(m.plan_created_at)}
            />
            <KeyValue
              label={t("analytics.migration.plan.plannedRequests")}
              value={m.planned_requests === null ? "—" : int(m.planned_requests)}
            />
            <KeyValue
              label={t("analytics.migration.plan.requestsSpent")}
              value={int(m.requests_spent)}
            />
            <KeyValue
              label={t("analytics.migration.plan.rowsWritten")}
              value={int(m.rows_written)}
            />
            <KeyValue
              label={t("analytics.migration.plan.lastActivity")}
              value={utcDateTime(m.last_activity_at)}
            />
          </Panel>
          <Panel
            title={t("analytics.migration.units.title")}
            subtitle={t("analytics.migration.units.subtitle")}
            bodyClassName=""
          >
            <TableShell>
              <THead>
                <TH>{t("analytics.common.kind")}</TH>
                <TH>{t("analytics.common.status")}</TH>
              </THead>
              <tbody>
                {Object.entries(m.units).map(([kind, states]) => (
                  <TRow key={kind}>
                    <TD>{kind.replaceAll("_", " ")}</TD>
                    <TD>
                      <span className="flex flex-wrap gap-2">
                        {Object.entries(states).map(([s, n]) => (
                          <StatusBadge
                            key={s}
                            tone={
                              s === "done" ? "positive" : s === "failed" ? "negative" : "neutral"
                            }
                          >
                            {s} {int(n)}
                          </StatusBadge>
                        ))}
                      </span>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Panel>
        </div>
      )}
    </Loading>
  );
}
