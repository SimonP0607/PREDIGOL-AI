/** The match in context: recent form, the table, head to head, absences, line-up status. */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { CheckCircle2, Shirt, Swords, TrendingUp, Trophy, UserX } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { fmtLine } from "@/lib/i18n/format";
import { formatDateYear, formatRelative } from "@/lib/time";
import type { TeamRef } from "@/lib/api/v1/types";
import type { Absence, H2HMatch, Side, StandingLine } from "@/lib/api/v1/types_center";
import { PlayerPhoto, TeamName } from "@/components/football/Logos";
import { sectionCodeText } from "@/components/system/sectionCode";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { PlayerSummary, SeasonLine } from "./PlayerSummary";
import { absenceKind, absenceReason, h2hSummary, lastFive } from "./model";
import { matchTables, rankedRows } from "@/product/shared/standings";
import { Block, CenterSection, FormChips, MoreButton, PlayerName, SectionNote } from "./ui";

const SIDES: readonly Side[] = ["home", "away"];

function teamOf(ctx: MatchCtx, side: Side): TeamRef {
  return side === "home" ? ctx.match.home : ctx.match.away;
}

// ── Form ────────────────────────────────────────────────────────────────────

function FormBody({ ctx }: { ctx: MatchCtx }) {
  const { center } = ctx;
  if (center.loading) return <SkeletonBlock className="h-24" />;
  if (center.error)
    return <ErrorState error={center.error} onRetry={center.retry} className="py-5" />;
  const c = center.data;
  const forms = c?.form.status === "ok" ? c.form.data : [];
  const table = c?.standings.status === "ok" ? c.standings.data : [];
  const rows = SIDES.map((side) => ({
    side,
    chips: lastFive(
      forms.find((f) => f.side === side),
      table.find((s) => s.side === side),
    ),
  }));
  if (rows.every((r) => r.chips.length === 0)) {
    return <SectionNote status={c ? c.form.status : (center.status ?? "not_available")} />;
  }
  return (
    <div>
      <ul className="divide-y divide-border/60">
        {rows.map(({ side, chips }) => {
          const team = teamOf(ctx, side);
          const withGoals = chips.filter((x) => x.goalsFor !== null && x.goalsAgainst !== null);
          const gf = withGoals.reduce((n, x) => n + (x.goalsFor ?? 0), 0);
          const ga = withGoals.reduce((n, x) => n + (x.goalsAgainst ?? 0), 0);
          return (
            <li key={side} className="flex items-center justify-between gap-3 py-2.5 first:pt-0">
              <div className="min-w-0">
                <TeamName
                  name={team.name}
                  logo={team.logo_url}
                  size={22}
                  strong
                  wrap
                  className="text-sm"
                />
                {withGoals.length > 0 ? (
                  <p className="mt-0.5 pl-[30px] text-caption text-muted-foreground">
                    {t("match.form.goals", { scored: gf, conceded: ga })}
                  </p>
                ) : null}
              </div>
              {chips.length > 0 ? (
                <FormChips chips={chips} className="shrink-0" />
              ) : (
                <span className="text-caption text-subtle-foreground">
                  {t("match.note.noData")}
                </span>
              )}
            </li>
          );
        })}
      </ul>
      <p className="mt-1 text-right text-caption text-subtle-foreground">
        {t("match.form.newestRight")}
      </p>
    </div>
  );
}

export function FormBlock({ ctx }: { ctx: MatchCtx }) {
  return (
    <Block
      title={t("match.form.title")}
      icon={<TrendingUp />}
      right={
        <span className="text-caption text-subtle-foreground">{t("match.form.lastFive")}</span>
      }
    >
      <FormBody ctx={ctx} />
    </Block>
  );
}

// ── Table ───────────────────────────────────────────────────────────────────

/** Which table the rows come from: "Tabla: Clausura", each team's group, and why for a knock-out round. */
function TableCaption({ rows }: { rows: StandingLine[] }) {
  const labels = [...new Set(rows.map((r) => r.table).filter((x): x is string => !!x))];
  if (labels.length === 0) return null;
  const first = rows.find((r) => r.table);
  const stage = first?.fixture_stage ?? null;
  const reason =
    first?.selection && first.selection !== "fixture_stage" && stage
      ? t(`match.standings.selection.${first.selection}`, { stage, table: labels.join(" / ") })
      : null;
  return (
    <div className="mb-2 space-y-0.5" data-testid="table-caption">
      <p className="text-caption text-muted-foreground">
        {t("match.standings.tableOf", { table: labels.join(" · ") })}
        {labels.length > 1 ? (
          <span className="ml-1 text-subtle-foreground">{t("match.standings.eachGroup")}</span>
        ) : null}
      </p>
      {reason ? <p className="text-caption text-subtle-foreground">{reason}</p> : null}
    </div>
  );
}

/** The whole table(s) the two rows come from, opened on demand; both teams highlighted. */
function FullTables({ ctx, rows }: { ctx: MatchCtx; rows: StandingLine[] }) {
  const [open, setOpen] = useState(false);
  const tables = matchTables(rows, ctx.center.data?.standings_tables);
  if (tables.length === 0 || tables.every((tb) => tb.rows.length <= 2)) return null;
  const mine = new Set([ctx.match.home.id, ctx.match.away.id]);
  return (
    <div className="mt-2">
      <button
        type="button"
        className="tap relative inline-flex min-h-8 items-center text-caption text-primary hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {open ? t("match.standings.hideFull") : t("match.standings.showFull")}
      </button>
      {open
        ? tables.map((tb) => (
            <div key={tb.key} className="mt-2">
              {tables.length > 1 ? (
                <p className="mb-1 text-caption font-medium text-muted-foreground">{tb.label}</p>
              ) : null}
              <table className="w-full table-fixed text-xs">
                <tbody className="divide-y divide-border/40">
                  {rankedRows(tb.rows, "all").map(({ rank, row, figures: f }) => (
                    <tr
                      key={row.team_id}
                      className={cn(mine.has(row.team_id) && "bg-primary/8 font-semibold")}
                    >
                      <td className="numeric w-7 py-1 text-muted-foreground">{rank}</td>
                      <td className="py-1 pr-2">
                        <TeamName name={row.team} logo={row.team_logo} size={16} wrap />
                      </td>
                      <td className="numeric w-8 py-1 text-right text-muted-foreground">
                        {f.played}
                      </td>
                      <td className="numeric w-10 py-1 text-right">{fmtLine(f.goalDiff, true)}</td>
                      <td className="numeric w-9 py-1 text-right font-semibold">{f.points}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ))
        : null}
    </div>
  );
}

function StandingsTable({ ctx, rows }: { ctx: MatchCtx; rows: StandingLine[] }) {
  const sorted = [...rows].sort((a, b) => a.rank - b.rank);
  const after = rows.some((r) => !r.before_kickoff);
  return (
    <>
      <TableCaption rows={rows} />
      <table className="w-full table-fixed text-sm">
        <thead>
          <tr className="text-caption text-subtle-foreground">
            <th scope="col" className="w-8 pb-1.5 text-left font-medium">
              <abbr title={t("match.standings.rankLong")} className="no-underline">
                {t("match.standings.rank")}
              </abbr>
            </th>
            <th scope="col" className="pb-1.5 text-left font-medium">
              {t("match.standings.team")}
            </th>
            <th scope="col" className="w-9 pb-1.5 text-right font-medium">
              <abbr title={t("match.standings.playedLong")} className="no-underline">
                {t("match.standings.played")}
              </abbr>
            </th>
            <th scope="col" className="w-11 pb-1.5 text-right font-medium">
              <abbr title={t("match.standings.goalDiffLong")} className="no-underline">
                {t("match.standings.goalDiff")}
              </abbr>
            </th>
            <th scope="col" className="w-10 pb-1.5 text-right font-medium">
              <abbr title={t("match.standings.pointsLong")} className="no-underline">
                {t("match.standings.points")}
              </abbr>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {sorted.map((s) => {
            const team = teamOf(ctx, s.side);
            return (
              <tr key={s.side}>
                <td className="numeric py-2 text-muted-foreground">{s.rank}</td>
                <td className="py-2 pr-2">
                  {/* Whole, wrapping: beside the form chips or in a fixed table, "Zorya Luh…" at 320 px. */}
                  <TeamName
                    name={team.name}
                    logo={team.logo_url}
                    size={20}
                    wrap
                    className="min-w-0"
                  />
                </td>
                <td className="numeric py-2 text-right text-muted-foreground">{s.played}</td>
                <td className="numeric py-2 text-right">
                  {fmtLine(s.goals_for - s.goals_against, true)}
                </td>
                <td className="numeric py-2 text-right font-semibold">{s.points}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {after ? (
        <p className="mt-2 text-caption text-subtle-foreground">
          {t("match.standings.includesMatch")}
        </p>
      ) : null}
      <TableFreshness rows={rows} />
      <FullTables ctx={ctx} rows={rows} />
    </>
  );
}

/** "Tabla actualizada hace 2 h", and a plain note when it does not show the last match yet. */
function TableFreshness({ rows }: { rows: StandingLine[] }) {
  const newest = rows.reduce<string | null>(
    (acc, r) => (acc === null || r.snapshot_at > acc ? r.snapshot_at : acc),
    null,
  );
  if (!newest) return null;
  const state = rows.find((r) => r.table_state && r.table_state !== "FRESH")?.table_state;
  return (
    <p className="mt-2 text-caption text-subtle-foreground" data-testid="table-freshness">
      {t("match.standings.updated", { ago: formatRelative(newest) })}
      {state === "STALE" ? (
        <span className="ml-1 text-warning">{t("match.standings.stale")}</span>
      ) : state === "UNAVAILABLE" ? (
        <span className="ml-1">{t("match.standings.providerLag")}</span>
      ) : null}
    </p>
  );
}

export function StandingsBlock({ ctx }: { ctx: MatchCtx }) {
  return (
    <Block title={t("match.standings.title")} icon={<Trophy />}>
      <CenterSection center={ctx.center} pick={(c) => c.standings}>
        {(rows) => <StandingsTable ctx={ctx} rows={rows} />}
      </CenterSection>
    </Block>
  );
}

// ── Head to head ────────────────────────────────────────────────────────────

function H2HBody({ ctx, rows }: { ctx: MatchCtx; rows: H2HMatch[] }) {
  const { home, away } = ctx.match;
  const recent = [...rows]
    .sort((a, b) => Date.parse(b.kickoff_at) - Date.parse(a.kickoff_at))
    .slice(0, 5);
  const sum = h2hSummary(rows, home.name, away.name);
  const pct = (n: number) => (sum.counted > 0 ? (n / sum.counted) * 100 : 0);
  return (
    <div className="space-y-3">
      {sum.counted > 0 ? (
        <div>
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              {
                n: sum.homeWins,
                label: t("match.h2h.wins", { team: home.name }),
                tone: "text-primary",
              },
              { n: sum.draws, label: t("match.h2h.draws"), tone: "text-muted-foreground" },
              {
                n: sum.awayWins,
                label: t("match.h2h.wins", { team: away.name }),
                tone: "text-info",
              },
            ].map((x) => (
              <div key={x.label} className="min-w-0">
                <div className={cn("numeric text-xl font-semibold", x.tone)}>{x.n}</div>
                <div className="break-words text-caption leading-tight text-muted-foreground">
                  {x.label}
                </div>
              </div>
            ))}
          </div>
          <div aria-hidden className="mt-2 flex h-1.5 overflow-hidden rounded-full bg-muted">
            <span className="h-full bg-primary" style={{ width: `${pct(sum.homeWins)}%` }} />
            <span
              className="h-full bg-subtle-foreground/60"
              style={{ width: `${pct(sum.draws)}%` }}
            />
            <span className="h-full bg-info" style={{ width: `${pct(sum.awayWins)}%` }} />
          </div>
        </div>
      ) : null}
      <ul className="divide-y divide-border/60">
        {recent.map((r) => (
          <li key={r.fixture_id}>
            <Link
              to="/matches/$fixtureId"
              params={{ fixtureId: String(r.fixture_id) }}
              className="block rounded-md py-2 transition-colors hover:bg-elevated/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-2 text-sm">
                <span
                  className={cn(
                    "break-words text-right leading-snug",
                    r.goals_home > r.goals_away ? "font-semibold" : "text-muted-foreground",
                  )}
                >
                  {r.home}
                </span>
                <span className="numeric rounded-md bg-elevated px-2 py-0.5 text-xs font-semibold">
                  {r.goals_home}–{r.goals_away}
                </span>
                <span
                  className={cn(
                    "break-words leading-snug",
                    r.goals_away > r.goals_home ? "font-semibold" : "text-muted-foreground",
                  )}
                >
                  {r.away}
                </span>
              </div>
              <div className="mt-0.5 break-words text-center text-caption text-subtle-foreground">
                {formatDateYear(r.kickoff_at)} · {r.competition}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function H2HBlock({ ctx }: { ctx: MatchCtx }) {
  const rows = ctx.center.data?.h2h?.status === "ok" ? ctx.center.data.h2h.data : [];
  return (
    <Block
      title={t("match.h2h.title")}
      icon={<Swords />}
      right={
        rows.length > 0 ? (
          <span className="text-caption text-subtle-foreground">
            {t("match.h2h.meetings", { count: rows.length })}
          </span>
        ) : null
      }
    >
      <CenterSection
        center={ctx.center}
        pick={(c) => c.h2h ?? { status: "not_available" as const, data: [], reason: null }}
      >
        {(data) => <H2HBody ctx={ctx} rows={data} />}
      </CenterSection>
    </Block>
  );
}

// ── Absences ────────────────────────────────────────────────────────────────

const KIND_TONE = {
  missing: "border-negative/35 bg-negative-soft text-negative",
  questionable: "border-warning/40 bg-warning-soft text-warning",
  other: "border-border-strong bg-elevated text-muted-foreground",
} as const;

function AbsenceList({ ctx, rows }: { ctx: MatchCtx; rows: Absence[] }) {
  const groups: Array<{ side: Side | null; rows: Absence[] }> = [
    { side: "home", rows: rows.filter((a) => a.side === "home") },
    { side: "away", rows: rows.filter((a) => a.side === "away") },
    { side: null, rows: rows.filter((a) => a.side === null) },
  ].filter((g) => g.rows.length > 0) as Array<{ side: Side | null; rows: Absence[] }>;
  return (
    <div className="space-y-3">
      {groups.map((g) => {
        const team = g.side ? teamOf(ctx, g.side) : null;
        return (
          <div key={g.side ?? "unknown"}>
            <div className="mb-1 flex items-center justify-between gap-2">
              {team ? (
                <TeamName
                  name={team.name}
                  logo={team.logo_url}
                  size={18}
                  strong
                  className="text-xs"
                />
              ) : (
                <span className="text-xs font-semibold text-muted-foreground">
                  {t("match.absences.unknownTeam")}
                </span>
              )}
              <span className="numeric text-caption text-subtle-foreground">{g.rows.length}</span>
            </div>
            <ul className="divide-y divide-border/60">
              {g.rows.map((a, i) => {
                const kind = absenceKind(a);
                return (
                  <li
                    key={`${a.player_id ?? a.player ?? "p"}-${i}`}
                    className="flex items-center justify-between gap-2 py-1.5 text-sm"
                    data-testid="absence"
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <PlayerPhoto src={a.photo_url ?? null} name={a.player ?? "?"} size={32} />
                      <span className="min-w-0">
                        <PlayerSummary
                          name={a.player}
                          photo={a.photo_url}
                          position={a.position}
                          season={a.season}
                          competition={ctx.match.competition.name}
                          playerId={a.player_id}
                          admin={ctx.showAdmin}
                          className="tap-y relative block max-w-full break-words font-medium leading-snug"
                        >
                          {a.player ?? t("match.events.unknownPlayer")}
                        </PlayerSummary>
                        <SeasonLine season={a.season} />
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1.5">
                      <span
                        className="text-caption text-muted-foreground"
                        title={a.reason ?? undefined}
                      >
                        {t(`match.absences.reason.${absenceReason(a.reason)}`)}
                      </span>
                      <span
                        className={cn(
                          "rounded-full border px-1.5 py-px text-[0.65rem] font-semibold",
                          KIND_TONE[kind],
                        )}
                      >
                        {t(`match.absences.kind.${kind}`)}
                      </span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

export function AbsencesBlock({ ctx }: { ctx: MatchCtx }) {
  const n = ctx.center.data?.absences.status === "ok" ? ctx.center.data.absences.data.length : 0;
  return (
    <Block
      title={t("match.absences.title")}
      icon={<UserX />}
      right={
        n > 0 ? (
          <span className="text-caption text-subtle-foreground">
            {t("match.absences.count", { count: n })}
          </span>
        ) : null
      }
    >
      <CenterSection center={ctx.center} pick={(c) => c.absences}>
        {(rows) => <AbsenceList ctx={ctx} rows={rows} />}
      </CenterSection>
    </Block>
  );
}

// ── Line-ups teaser ─────────────────────────────────────────────────────────

export function LineupsTeaser({ ctx }: { ctx: MatchCtx }) {
  return (
    <Block title={t("match.lineups.title")} icon={<Shirt />}>
      <CenterSection
        center={ctx.center}
        pick={(c) => c.lineups}
        empty={(_, code) => {
          const why = sectionCodeText(code);
          return (
            <div className="space-y-1">
              <p className="text-sm text-muted-foreground">{t("match.lineups.unavailable")}</p>
              {why ? <p className="text-caption text-subtle-foreground">{why}</p> : null}
            </div>
          );
        }}
      >
        {(lineups) => (
          <div className="space-y-2.5">
            <p className="flex items-center gap-1.5 text-sm font-medium text-positive">
              <CheckCircle2 aria-hidden className="h-4 w-4" />
              {t("match.lineups.confirmed")}
            </p>
            <ul className="space-y-1.5">
              {SIDES.map((side) => {
                const team = teamOf(ctx, side);
                const l = lineups.find((x) => x.side === side);
                return (
                  <li key={side} className="flex items-center justify-between gap-2">
                    <TeamName
                      name={team.name}
                      logo={team.logo_url}
                      size={20}
                      className="min-w-0 text-sm"
                    />
                    <span className="numeric shrink-0 rounded-md border border-border-strong bg-elevated px-1.5 py-0.5 text-xs">
                      {l?.formation ?? "—"}
                    </span>
                  </li>
                );
              })}
            </ul>
            <MoreButton onClick={() => ctx.goTo("lineups")}>{t("match.lineups.view")}</MoreButton>
          </div>
        )}
      </CenterSection>
    </Block>
  );
}
