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
    <span className="text-subtle-foreground" title={reason ?? "No value recorded."}>
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
      <SegmentedTabs label="Analytics sections" tabs={tabs} value={tab} onChange={setTab} />
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
      title="Competition profiles"
      subtitle="Regulation-time outcomes of recorded results per competition and season, and how many fixtures carry each kind of data. Fewer than 30 results: shown with its n, flagged."
      bodyClassName=""
    >
      <Loading q={q}>
        {(rows) => (
          <TableShell>
            <THead>
              <TH>Competition</TH>
              <TH align="right">Season</TH>
              <TH align="right">Results</TH>
              <TH align="right">Home</TH>
              <TH align="right">Draw</TH>
              <TH align="right">Away</TH>
              <TH align="right">Goals</TH>
              <TH align="right">Home edge</TH>
              <TH align="right">BTTS</TH>
              <TH align="right">Over 2.5</TH>
              <TH align="right">Stats</TH>
              <TH align="right">Odds</TH>
              <TH align="right">Features</TH>
            </THead>
            <tbody>
              {rows.map((r) => (
                <TRow key={`${r.competition_id}-${r.season}`}>
                  <TD>
                    <div className="flex items-center gap-2 text-sm">
                      {r.competition}
                      {r.low_sample ? <StatusBadge tone="warning">small sample</StatusBadge> : null}
                    </div>
                    <div className="text-caption text-subtle-foreground">
                      {r.country ?? "International"}
                    </div>
                  </TD>
                  <TD align="right">
                    <Numeric muted>{r.season}</Numeric>
                  </TD>
                  <TD align="right">
                    <Numeric>{int(r.finished)}</Numeric>
                    <div className="text-caption text-subtle-foreground">of {int(r.fixtures)}</div>
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

const FEATURE_LABEL: Record<string, string> = {
  elo: "Elo",
  pi: "pi-rating (at this venue)",
  shot_share10: "Shot share, last 10",
  sot_share10: "On-target share, last 10",
  elo_resid10: "Form beyond Elo, last 10",
  ppg5: "Points per match, last 5",
  rest_days: "Rest days",
  history_n: "Matches in history",
};

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
          Team
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
        <StatusNotice status="empty" reason="No team has been ingested yet." />
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
        title={`${d.team.name}: record`}
        subtitle="Regulation time, from recorded results only"
        bodyClassName=""
      >
        {status !== "ok" ? (
          <StatusNotice status="insufficient_data" reason={reason} compact />
        ) : (
          <TableShell>
            <THead>
              <TH>Split</TH>
              <TH align="right">P</TH>
              <TH align="right">W</TH>
              <TH align="right">D</TH>
              <TH align="right">L</TH>
              <TH align="right">GF</TH>
              <TH align="right">GA</TH>
              <TH align="right" title="Points per match">
                PPM
              </TH>
            </THead>
            <tbody>
              {(["all", "home", "away"] as const).map((k) => {
                const s = d.splits[k];
                return (
                  <TRow key={k}>
                    <TD>{k === "all" ? "All" : k === "home" ? "Home" : "Away"}</TD>
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
                      <Cell value={num(s.points_per_match)} reason="No match in this split." />
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
          title="Elo after each rated match"
          subtitle={`${d.elo.length} rated matches, ${utcDate(d.elo[0]?.kickoff_at)} to ${utcDate(d.elo[d.elo.length - 1]?.kickoff_at)}`}
        >
          <EloChart points={d.elo} />
        </ChartContainer>
      ) : (
        <Panel title="Elo">
          <StatusNotice status="empty" reason="No rated match for this team yet." compact />
        </Panel>
      )}
      <Panel
        title="As the models see it"
        subtitle={
          d.features
            ? `Feature set ${d.features.feature_version} for fixture ${d.features.fixture_id}, cut-off ${utcDateTime(d.features.data_cutoff)} (${d.features.side} side)`
            : "Newest feature set"
        }
      >
        {d.features ? (
          <div className="grid gap-x-8 sm:grid-cols-2">
            {Object.entries(d.features.values)
              .filter(([k]) => k in FEATURE_LABEL)
              .map(([k, v]) => (
                <KeyValue
                  key={k}
                  label={FEATURE_LABEL[k] ?? k}
                  value={
                    <Cell
                      value={num(v, FEATURE_DIGITS[k] ?? 3)}
                      reason="Not enough history for this feature."
                    />
                  }
                />
              ))}
          </div>
        ) : (
          <StatusNotice status="empty" reason="No feature set includes this team yet." compact />
        )}
      </Panel>
      <Panel
        title="Shots, last 10 matches with statistics"
        subtitle="Team statistics as recorded, API-Football preferred over Football-Data when both exist"
        bodyClassName=""
      >
        {last.length ? (
          <TableShell>
            <THead>
              <TH>Match</TH>
              <TH align="right">Shots</TH>
              <TH align="right">On target</TH>
              <TH>Source</TH>
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
            reason="No match of this team has team statistics yet."
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
      title="Research registry"
      subtitle="Every stored experiment and its model gate. A model leaves RESEARCH only with all six checks passed - out of sample, temporal validation, calibration, reproduction, stability, and beating the market."
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
                  <TH>Experiment</TH>
                  <TH>Status</TH>
                  <TH align="right">Log loss</TH>
                  <TH align="right">vs market (Δ, 95%)</TH>
                  <TH>Verdict</TH>
                  <TH>Gate</TH>
                </THead>
                <tbody>
                  {rows.map((e) => (
                    <TRow key={e.id}>
                      <TD>
                        <div className="text-sm">{e.model_family}</div>
                        <div className="numeric text-caption text-subtle-foreground">
                          #{e.id} · session {e.backtest_session_id ?? "—"} ·{" "}
                          {shortHash(e.code_version, 7)}
                          {e.reproduction_of ? ` · reproduces #${e.reproduction_of}` : ""}
                        </div>
                      </TD>
                      <TD>
                        <StatusBadge tone={STATUS_TONE[e.research_status]}>
                          {e.research_status}
                        </StatusBadge>
                        {e.reproduced_by !== null ? (
                          <div className="mt-1 text-caption text-positive">
                            reproduced by #{e.reproduced_by}
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
                          evidence {e.evidence ?? "—"}
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
                  {reruns} reproduction run{reruns === 1 ? "" : "s"} not listed: each is linked from
                  the experiment it re-ran.
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
            title="Is the closing line calibrated?"
            subtitle={`${m.baseline}, one-vs-rest over home, draw and away on ${int(m.n_fixtures)} fixtures. On the diagonal: stated probabilities come true at their rate.`}
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
          <Panel title="Calibration buckets" subtitle={m.source} bodyClassName="">
            <TableShell>
              <THead>
                <TH>Bucket</TH>
                <TH align="right">n</TH>
                <TH align="right">Mean stated</TH>
                <TH align="right">Observed</TH>
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
                        reason="No selection in this bucket."
                      />
                    </TD>
                    <TD align="right">
                      <Cell
                        value={ratio(b.observed_rate, 1)}
                        reason="No selection in this bucket."
                      />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          </Panel>
          <Panel
            title="What the last hours of trading add"
            subtitle="Log loss of the de-vigged Pinnacle pre-closing and closing prices on the same fixtures; the difference is what the market learned before kick-off."
            bodyClassName=""
            className="xl:col-span-2"
          >
            <TableShell>
              <THead>
                <TH>Competition</TH>
                <TH align="right">Season</TH>
                <TH align="right">n</TH>
                <TH align="right">Pre-closing</TH>
                <TH align="right">Closing</TH>
                <TH align="right">Improvement</TH>
                <TH align="right">Margin</TH>
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
                        reason="No closing prices for this season."
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
    ["with_result", "Results"],
    ["with_team_stats", "Team stats"],
    ["with_events", "Events"],
    ["with_lineups", "Lineups"],
    ["with_player_stats", "Players"],
    ["with_historical_odds", "Hist. odds"],
    ["with_odds_snapshots", "Snapshots"],
    ["with_features", "Features"],
    ["with_predictions", "Predictions"],
  ] as const;
  return (
    <Panel
      title="Data coverage"
      subtitle="Per competition and season, how many fixtures carry each kind of data. Events, lineups and player statistics arrive with the paid historical migration."
      bodyClassName=""
    >
      <Loading q={q}>
        {(rows) => (
          <TableShell>
            <THead>
              <TH>Competition</TH>
              <TH align="right">Season</TH>
              <TH align="right">Fixtures</TH>
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
            title="Plan"
            subtitle="The newest stored migration plan (python -m scripts.migration seed)"
          >
            <KeyValue
              label="Plan"
              value={m.plan_name ?? "No plan stored yet - units seeded directly"}
            />
            <KeyValue label="Created" value={utcDateTime(m.plan_created_at)} />
            <KeyValue
              label="Planned requests"
              value={m.planned_requests === null ? "—" : int(m.planned_requests)}
            />
            <KeyValue label="Requests spent" value={int(m.requests_spent)} />
            <KeyValue label="Rows written" value={int(m.rows_written)} />
            <KeyValue label="Last activity" value={utcDateTime(m.last_activity_at)} />
          </Panel>
          <Panel title="Units" subtitle="Resumable units by kind and status" bodyClassName="">
            <TableShell>
              <THead>
                <TH>Kind</TH>
                <TH>Status</TH>
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
