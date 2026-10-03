/**
 * The Match Center's football sections - statistics, events, line-ups, player
 * ratings, context (table, form, head-to-head, absences) and in-play data -
 * read from GET /matches/{id}/center. Every block renders its own status: a
 * match with no line-ups says why instead of showing an empty table.
 */
import { Link } from "@tanstack/react-router";
import { KeyValue, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { FormStrip, Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  LineupPlayer,
  LiveMove,
  LiveQuote,
  MatchCenter,
  MatchEvent,
  PlayerLine,
  Side,
  TeamStatLine,
} from "@/lib/api/v1/types_center";
import { cn } from "@/lib/utils";
import { dec, relative, utcDate, utcDateTime } from "./format";
import { minuteText, quoteLabel } from "./liveText";

export interface Sides {
  home: string;
  away: string;
}

/** Loads the Match Center detail once (shared query) and renders it. */
export function WithCenter({
  fixtureId,
  children,
}: {
  fixtureId: string;
  children: (c: MatchCenter) => React.ReactNode;
}) {
  const q = useLiveQuery(live.center(fixtureId));
  if (q.isLoading) return <TableSkeleton rows={6} cols={6} />;
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!q.data) return null;
  if (!q.data.data) return <StatusNotice status={q.data.status} reason={q.data.reason} />;
  return <>{children(q.data.data)}</>;
}

// ── Statistics ─────────────────────────────────────────────────────────────

const STAT_ROWS: Array<{
  key: keyof TeamStatLine;
  label: string;
  decimals?: number;
  pct?: boolean;
}> = [
  { key: "possession_pct", label: "Possession", pct: true },
  { key: "expected_goals", label: "Expected goals (xG)", decimals: 2 },
  { key: "shots", label: "Shots" },
  { key: "shots_on_target", label: "Shots on target" },
  { key: "shots_off_target", label: "Shots off target" },
  { key: "shots_blocked", label: "Shots blocked" },
  { key: "shots_inside_box", label: "Shots inside the box" },
  { key: "shots_outside_box", label: "Shots outside the box" },
  { key: "corners", label: "Corners" },
  { key: "fouls", label: "Fouls" },
  { key: "offsides", label: "Offsides" },
  { key: "yellow_cards", label: "Yellow cards" },
  { key: "red_cards", label: "Red cards" },
  { key: "saves", label: "Goalkeeper saves" },
  { key: "passes", label: "Passes" },
  { key: "passes_accurate", label: "Accurate passes" },
];

function statValue(line: TeamStatLine | undefined, key: keyof TeamStatLine): number | null {
  if (!line) return null;
  const v = line[key];
  if (v === null || v === undefined || typeof v === "boolean") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function StatComparison({
  lines,
  sides,
  rows = STAT_ROWS,
}: {
  lines: TeamStatLine[];
  sides: Sides;
  rows?: typeof STAT_ROWS;
}) {
  const home = lines.find((l) => l.side === "home");
  const away = lines.find((l) => l.side === "away");
  const shown = rows.filter(
    (r) => statValue(home, r.key) !== null || statValue(away, r.key) !== null,
  );
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between text-caption uppercase tracking-wider text-subtle-foreground">
        <span className="truncate">{sides.home}</span>
        <span className="truncate text-right">{sides.away}</span>
      </div>
      {shown.map((r) => {
        const h = statValue(home, r.key);
        const a = statValue(away, r.key);
        const total = (h ?? 0) + (a ?? 0);
        const hShare = total > 0 ? ((h ?? 0) / total) * 100 : 50;
        const fmt = (v: number | null) =>
          v === null ? null : r.pct ? `${v.toFixed(0)}%` : v.toFixed(r.decimals ?? 0);
        return (
          <div key={String(r.key)} data-stat={String(r.key)}>
            <div className="flex items-baseline justify-between text-xs">
              <Numeric className="text-xs">
                <Nullable value={fmt(h)} reason="Not reported for this side." />
              </Numeric>
              <span className="text-caption text-muted-foreground">{r.label}</span>
              <Numeric className="text-xs">
                <Nullable value={fmt(a)} reason="Not reported for this side." />
              </Numeric>
            </div>
            <div className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div className="h-full bg-primary/80" style={{ width: `${hShare}%` }} />
              <div className="h-full flex-1 bg-info/60" />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function StatsTab({ c, sides }: { c: MatchCenter; sides: Sides }) {
  return (
    <Panel
      title="Team statistics"
      subtitle={
        c.statistics.status === "ok"
          ? `As of ${utcDateTime(c.statistics.data[0]?.fetched_at)} — ${
              c.status_group === "live" ? "updated every minute while the match is played" : "final"
            }.`
          : "From the provider's match detail."
      }
    >
      <SectionView section={c.statistics}>
        {(lines) => <StatComparison lines={lines} sides={sides} />}
      </SectionView>
    </Panel>
  );
}

// ── Events ─────────────────────────────────────────────────────────────────

function eventTone(e: MatchEvent): BadgeTone {
  if (e.type === "Goal") return e.detail === "Missed Penalty" ? "neutral" : "positive";
  if (e.type === "Card")
    return e.detail?.startsWith("Red") || e.detail?.startsWith("Second") ? "negative" : "warning";
  if (e.type === "Var") return "info";
  return "neutral";
}

function eventLabel(e: MatchEvent): string {
  if (e.type === "subst") return "Sub";
  if (e.type === "Card") return e.detail?.replace(" Card", "") ?? "Card";
  if (e.type === "Goal") {
    if (e.detail === "Own Goal") return "Own goal";
    if (e.detail === "Penalty") return "Pen";
    if (e.detail === "Missed Penalty") return "Pen missed";
    return "Goal";
  }
  return e.type;
}

function PlayerName({ name, id }: { name: string | null; id: number | null }) {
  if (!name) return <Nullable value={null} reason="The provider did not name the player." />;
  if (id === null) return <span>{name}</span>;
  return (
    <Link
      to="/players/$playerId"
      params={{ playerId: String(id) }}
      className="hover:text-primary hover:underline"
    >
      {name}
    </Link>
  );
}

export function EventList({ events, sides }: { events: MatchEvent[]; sides: Sides }) {
  return (
    <ol className="divide-y divide-border/60">
      {events.map((e) => (
        <li
          key={e.seq}
          className={cn(
            "grid grid-cols-[3.25rem_1fr] items-start gap-3 py-2 text-xs sm:grid-cols-[3.25rem_1fr_1fr]",
          )}
        >
          <span className="numeric pt-0.5 text-muted-foreground">
            {minuteText(e.minute, e.extra_minute)}
          </span>
          <div className={cn("min-w-0", e.side === "away" ? "sm:col-start-3" : "")}>
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge tone={eventTone(e)}>{eventLabel(e)}</StatusBadge>
              <span className="font-medium">
                <PlayerName name={e.player} id={e.player_id} />
              </span>
            </div>
            <div className="mt-0.5 text-caption text-muted-foreground">
              {e.side ? (e.side === "home" ? sides.home : sides.away) : "side not reported"}
              {e.type === "subst" && e.assist ? ` · for ${e.assist}` : ""}
              {e.type === "Goal" && e.assist ? ` · assist ${e.assist}` : ""}
              {e.type === "Var" && e.detail ? ` · ${e.detail}` : ""}
              {e.comments ? ` · ${e.comments}` : ""}
            </div>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function EventsTab({ c, sides }: { c: MatchCenter; sides: Sides }) {
  return (
    <Panel
      title="Events"
      subtitle="Goals, cards, substitutions and VAR decisions as the provider reports them."
    >
      <SectionView section={c.events}>
        {(ev) => <EventList events={ev} sides={sides} />}
      </SectionView>
    </Panel>
  );
}

// ── Line-ups ───────────────────────────────────────────────────────────────

function LineupTable({ players }: { players: LineupPlayer[] }) {
  return (
    <TableShell compact>
      <THead>
        <TH align="right">#</TH>
        <TH>Player</TH>
        <TH>Pos</TH>
        <TH>Grid</TH>
      </THead>
      <tbody>
        {players.map((p) => (
          <TRow key={p.provider_player_id}>
            <TD align="right">
              <Numeric muted className="text-xs">
                {p.number ?? "—"}
              </Numeric>
            </TD>
            <TD className="text-sm">
              <PlayerName name={p.name} id={p.player_id} />
            </TD>
            <TD className="text-xs text-muted-foreground">{p.position ?? "—"}</TD>
            <TD className="text-xs text-subtle-foreground">{p.grid ?? "—"}</TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

export function LineupsTab({ c, sides }: { c: MatchCenter; sides: Sides }) {
  return (
    <SectionView section={c.lineups}>
      {(lineups) => (
        <div className="grid gap-4 lg:grid-cols-2">
          {lineups.map((l) => {
            const starters = l.players.filter((p) => p.starter);
            const bench = l.players.filter((p) => !p.starter);
            return (
              <Panel
                key={l.side}
                title={l.side === "home" ? sides.home : sides.away}
                subtitle={`${l.formation ?? "formation not reported"} · coach ${l.coach ?? "not reported"}`}
                bodyClassName=""
              >
                <div className="px-4 pt-3 text-caption uppercase tracking-wider text-subtle-foreground">
                  Starting XI ({starters.length})
                </div>
                <LineupTable players={starters} />
                <div className="px-4 pt-3 text-caption uppercase tracking-wider text-subtle-foreground">
                  Bench ({bench.length})
                </div>
                {bench.length ? (
                  <LineupTable players={bench} />
                ) : (
                  <p className="px-4 pb-3 text-xs text-muted-foreground">No substitutes listed.</p>
                )}
              </Panel>
            );
          })}
        </div>
      )}
    </SectionView>
  );
}

// ── Players ────────────────────────────────────────────────────────────────

function PlayersTable({ rows }: { rows: PlayerLine[] }) {
  return (
    <TableShell>
      <THead>
        <TH>Player</TH>
        <TH align="right">Min</TH>
        <TH align="right" title="Provider rating, 0–10">
          Rating
        </TH>
        <TH align="right">G</TH>
        <TH align="right">A</TH>
        <TH align="right">Shots</TH>
        <TH align="right">On tgt</TH>
        <TH align="right">Key passes</TH>
        <TH align="right">Tackles</TH>
        <TH align="right">Saves</TH>
        <TH align="right">Cards</TH>
      </THead>
      <tbody>
        {rows.map((p) => (
          <TRow key={p.provider_player_id}>
            <TD className="text-sm">
              <PlayerName name={p.name} id={p.player_id} />
              {p.substitute ? (
                <span className="ml-1.5 text-caption text-subtle-foreground">sub</span>
              ) : null}
            </TD>
            <TD align="right">
              <Numeric className="text-xs">{p.minutes ?? "—"}</Numeric>
            </TD>
            <TD align="right">
              <Numeric className="text-xs">
                <Nullable
                  value={dec(p.rating, 1)}
                  reason="Not rated (too few minutes or not reported)."
                />
              </Numeric>
            </TD>
            {[p.goals, p.assists, p.shots, p.shots_on, p.key_passes, p.tackles, p.saves].map(
              (v, i) => (
                <TD key={i} align="right">
                  <Numeric muted={!v} className="text-xs">
                    {v ?? "—"}
                  </Numeric>
                </TD>
              ),
            )}
            <TD align="right" className="text-xs">
              {(p.yellow_cards ?? 0) > 0 ? (
                <span className="text-warning">Y{p.yellow_cards}</span>
              ) : null}
              {(p.red_cards ?? 0) > 0 ? (
                <span className="ml-1 text-negative">R{p.red_cards}</span>
              ) : null}
              {!p.yellow_cards && !p.red_cards ? (
                <span className="text-subtle-foreground">—</span>
              ) : null}
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

export function PlayersTab({ c, sides }: { c: MatchCenter; sides: Sides }) {
  return (
    <SectionView section={c.players}>
      {(rows) => (
        <div className="space-y-4">
          {(["home", "away"] as Side[]).map((side) => (
            <Panel key={side} title={side === "home" ? sides.home : sides.away} bodyClassName="">
              <PlayersTable rows={rows.filter((r) => r.side === side)} />
            </Panel>
          ))}
        </div>
      )}
    </SectionView>
  );
}

// ── Context ────────────────────────────────────────────────────────────────

export function ContextTab({ c, sides }: { c: MatchCenter; sides: Sides }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Panel
        title="League table"
        subtitle="The last table we hold before kick-off for both sides."
        bodyClassName=""
      >
        <SectionView section={c.standings}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH align="right">#</TH>
                <TH>Team</TH>
                <TH align="right">P</TH>
                <TH align="right">W-D-L</TH>
                <TH align="right">GD</TH>
                <TH align="right">Pts</TH>
                <TH>Form</TH>
              </THead>
              <tbody>
                {rows.map((s) => (
                  <TRow key={s.side}>
                    <TD align="right">
                      <Numeric>{s.rank}</Numeric>
                    </TD>
                    <TD className="text-sm">
                      {s.team}
                      {s.group ? (
                        <div className="text-caption text-subtle-foreground">{s.group}</div>
                      ) : null}
                    </TD>
                    <TD align="right">
                      <Numeric muted className="text-xs">
                        {s.played}
                      </Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric className="text-xs">
                        {s.wins}-{s.draws}-{s.losses}
                      </Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric className="text-xs">{s.goals_for - s.goals_against}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{s.points}</Numeric>
                    </TD>
                    <TD>
                      {s.form ? (
                        <FormStrip
                          form={s.form
                            .split("")
                            .filter(
                              (x): x is "W" | "D" | "L" => x === "W" || x === "D" || x === "L",
                            )
                            .slice(-5)}
                        />
                      ) : (
                        <Nullable value={null} reason="The provider gave no form string." />
                      )}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </SectionView>
        {c.standings.status === "ok" ? (
          <p className="px-4 py-2 text-caption text-subtle-foreground">
            Snapshot {utcDateTime(c.standings.data[0]?.snapshot_at)}
            {c.standings.data.some((s) => !s.before_kickoff)
              ? " — taken AFTER kick-off, it includes this match."
              : ""}
          </p>
        ) : null}
      </Panel>

      <Panel
        title="Recent form"
        subtitle="Last six finished matches before this one, any competition."
      >
        <SectionView section={c.form}>
          {(teams) => (
            <div className="space-y-4">
              {teams.map((t) => (
                <div key={t.side}>
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{t.team}</span>
                    <FormStrip form={t.matches.map((m) => m.result).reverse()} />
                  </div>
                  {t.matches.length ? (
                    <ul className="space-y-1 text-xs">
                      {t.matches.map((m) => (
                        <li key={m.fixture_id} className="flex items-center justify-between gap-2">
                          <Link
                            to="/matches/$fixtureId"
                            params={{ fixtureId: String(m.fixture_id) }}
                            className="min-w-0 truncate text-muted-foreground hover:text-primary"
                          >
                            {utcDate(m.kickoff_at)} · {m.venue === "H" ? "v" : "@"} {m.opponent}
                          </Link>
                          <span className="numeric shrink-0">
                            {m.goals_for}–{m.goals_against} {m.result}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-xs text-muted-foreground">No finished match stored.</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </SectionView>
      </Panel>

      <Panel
        title="Head to head"
        subtitle="Previous meetings with a stored result."
        bodyClassName=""
      >
        <SectionView section={c.h2h}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>Date</TH>
                <TH>Match</TH>
                <TH align="right">Score</TH>
              </THead>
              <tbody>
                {rows.map((m) => (
                  <TRow key={m.fixture_id}>
                    <TD className="text-xs text-muted-foreground">{utcDate(m.kickoff_at)}</TD>
                    <TD className="text-sm">
                      <Link
                        to="/matches/$fixtureId"
                        params={{ fixtureId: String(m.fixture_id) }}
                        className="hover:text-primary"
                      >
                        {m.home} v {m.away}
                      </Link>
                      <div className="text-caption text-subtle-foreground">{m.competition}</div>
                    </TD>
                    <TD align="right">
                      <Numeric>
                        {m.goals_home}–{m.goals_away}
                      </Numeric>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </SectionView>
      </Panel>

      <Panel
        title="Absences"
        subtitle="Injuries and suspensions the provider reported for this match."
        bodyClassName=""
      >
        <SectionView section={c.absences}>
          {(rows) => (
            <TableShell>
              <THead>
                <TH>Team</TH>
                <TH>Player</TH>
                <TH>Type</TH>
                <TH>Reason</TH>
              </THead>
              <tbody>
                {rows.map((a, i) => (
                  <TRow key={`${a.player}-${i}`}>
                    <TD className="text-xs text-muted-foreground">
                      {a.side === "home" ? sides.home : a.side === "away" ? sides.away : "—"}
                    </TD>
                    <TD className="text-sm">
                      <PlayerName name={a.player} id={a.player_id} />
                    </TD>
                    <TD className="text-xs">{a.type ?? "—"}</TD>
                    <TD className="text-xs text-muted-foreground">{a.reason ?? "—"}</TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </SectionView>
      </Panel>
    </div>
  );
}

// ── In-play ────────────────────────────────────────────────────────────────

const MARKET_ORDER = ["1X2", "OU", "AH", "BTTS", "DC"];

function LiveQuotesTable({ quotes }: { quotes: LiveQuote[] }) {
  const ours = quotes.filter((q) => q.market_key !== null);
  const others = quotes.length - ours.length;
  ours.sort(
    (a, b) =>
      MARKET_ORDER.indexOf(a.market_key ?? "") - MARKET_ORDER.indexOf(b.market_key ?? "") ||
      Number(a.line) - Number(b.line) ||
      a.selection.localeCompare(b.selection),
  );
  return (
    <>
      <TableShell>
        <THead>
          <TH>Market</TH>
          <TH align="right">Odds</TH>
          <TH>State</TH>
          <TH>Last change</TH>
        </THead>
        <tbody>
          {ours.map((q) => (
            <TRow key={`${q.provider_bet_id}-${q.selection}-${q.line}`}>
              <TD className="text-sm">
                {quoteLabel(q)}
                {q.main_line ? (
                  <span className="ml-1.5 text-caption text-primary">main</span>
                ) : null}
              </TD>
              <TD align="right">
                <Numeric>
                  <Nullable
                    value={dec(q.odds, 2)}
                    reason="Withdrawn by the bookmaker at this instant."
                  />
                </Numeric>
              </TD>
              <TD>
                {q.odds === null ? (
                  <StatusBadge tone="neutral">withdrawn</StatusBadge>
                ) : q.suspended ? (
                  <StatusBadge tone="warning">suspended</StatusBadge>
                ) : (
                  <StatusBadge tone="positive">open</StatusBadge>
                )}
              </TD>
              <TD className="text-xs text-muted-foreground">
                {q.minute !== null ? `${q.minute}' · ` : ""}
                {relative(q.captured_at)}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
      {others > 0 ? (
        <p className="px-4 py-2 text-caption text-subtle-foreground">
          {others} more in-play prices belong to bets with no market of ours; they are stored, not
          shown.
        </p>
      ) : null}
    </>
  );
}

const MOVE_TONE: Record<LiveMove["kind"], BadgeTone> = {
  moved: "info",
  withdrawn: "neutral",
  offered: "positive",
  suspended: "warning",
  available: "positive",
  other: "neutral",
};

export function LiveTab({ c }: { c: MatchCenter }) {
  return (
    <div className="space-y-4">
      <div className="rounded-md border border-info/30 bg-info-soft px-3 py-2 text-xs text-info">
        In-play data is a separate system from the pre-match prices: it is never used to judge,
        train or backtest a pre-match model, and the last in-play price is not a closing line.
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Match state over time"
          subtitle="Each change of status, minute or score, with its feed."
          bodyClassName=""
        >
          <SectionView section={c.live_states}>
            {(states) => (
              <div className="max-h-[420px] overflow-auto">
                <TableShell compact>
                  <THead>
                    <TH>Minute</TH>
                    <TH>Score</TH>
                    <TH>Status</TH>
                    <TH>Feed</TH>
                    <TH>At</TH>
                  </THead>
                  <tbody>
                    {states.map((s) => (
                      <TRow key={`${s.source}-${s.observed_at}`}>
                        <TD>
                          <Numeric className="text-xs">{minuteText(s.elapsed, s.extra)}</Numeric>
                        </TD>
                        <TD>
                          <Numeric className="text-xs">
                            {s.goals_home ?? "?"}–{s.goals_away ?? "?"}
                          </Numeric>
                        </TD>
                        <TD className="text-xs">{s.status}</TD>
                        <TD>
                          <StatusBadge tone={s.source === "fixture_feed" ? "brand" : "info"}>
                            {s.source === "fixture_feed" ? "fixtures" : "odds"}
                          </StatusBadge>
                        </TD>
                        <TD className="text-caption text-subtle-foreground">
                          {utcDateTime(s.observed_at)}
                        </TD>
                      </TRow>
                    ))}
                  </tbody>
                </TableShell>
              </div>
            )}
          </SectionView>
        </Panel>
        <Panel
          title="In-play prices"
          subtitle="The latest price of each selection (no bookmaker dimension in this feed)."
          bodyClassName=""
        >
          <SectionView section={c.live_odds}>{(q) => <LiveQuotesTable quotes={q} />}</SectionView>
        </Panel>
      </div>
      <Panel
        title="Price movement"
        subtitle="Every change in our markets, newest first: moves, suspensions, withdrawals."
        bodyClassName=""
      >
        <SectionView section={c.live_movement}>
          {(moves) => (
            <div className="max-h-[480px] overflow-auto">
              <TableShell compact>
                <THead>
                  <TH>Minute</TH>
                  <TH>Score</TH>
                  <TH>Market</TH>
                  <TH align="right">From</TH>
                  <TH align="right">To</TH>
                  <TH align="right">Δ</TH>
                  <TH>Change</TH>
                </THead>
                <tbody>
                  {moves.map((m, i) => (
                    <TRow key={`${m.captured_at}-${m.selection}-${m.line}-${i}`}>
                      <TD>
                        <Numeric className="text-xs">
                          {m.minute !== null ? `${m.minute}'` : "—"}
                        </Numeric>
                      </TD>
                      <TD className="text-xs">{m.score ?? "—"}</TD>
                      <TD className="text-sm">{quoteLabel(m)}</TD>
                      <TD align="right">
                        <Numeric muted className="text-xs">
                          {dec(m.previous_odds, 2) ?? "—"}
                        </Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric className="text-xs">{dec(m.odds, 2) ?? "—"}</Numeric>
                      </TD>
                      <TD align="right">
                        <Numeric
                          className={cn(
                            "text-xs",
                            Number(m.delta) > 0
                              ? "text-positive"
                              : Number(m.delta) < 0
                                ? "text-negative"
                                : "",
                          )}
                        >
                          {m.delta !== null
                            ? `${Number(m.delta) > 0 ? "+" : ""}${dec(m.delta, 2)}`
                            : "—"}
                        </Numeric>
                      </TD>
                      <TD>
                        <StatusBadge tone={MOVE_TONE[m.kind]}>{m.kind}</StatusBadge>
                      </TD>
                    </TRow>
                  ))}
                </tbody>
              </TableShell>
            </div>
          )}
        </SectionView>
      </Panel>
    </div>
  );
}

/** A compact live score line for the Match Center header while the match is played. */
export function LiveScoreLine({ c, sides }: { c: MatchCenter; sides: Sides }) {
  if (c.live_states.status !== "ok") return null;
  const s = c.live_states.data[0];
  if (!s) return null;
  const finished = ["FT", "AET", "PEN", "Match Finished"].includes(s.status);
  return (
    <Panel>
      <div className="flex flex-col items-center gap-2 sm:flex-row sm:justify-center sm:gap-8">
        <span className="text-sm font-medium sm:w-48 sm:text-right">{sides.home}</span>
        <span className="numeric text-3xl">
          {s.goals_home ?? "?"} – {s.goals_away ?? "?"}
        </span>
        <span className="text-sm font-medium sm:w-48">{sides.away}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-caption text-muted-foreground">
        <StatusBadge tone={finished ? "neutral" : "brand"}>
          {finished
            ? s.status
            : s.status === "HT"
              ? "half time"
              : `live ${minuteText(s.elapsed, s.extra)}`}
        </StatusBadge>
        <span>
          {s.source === "fixture_feed" ? "fixture feed" : "odds feed"} · {relative(s.observed_at)}
        </span>
      </div>
    </Panel>
  );
}
