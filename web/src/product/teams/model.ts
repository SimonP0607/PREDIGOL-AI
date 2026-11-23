/**
 * The profiles of clubs, national teams and players (plan maestro unificado, UX-154 to UX-157; maquetas 11, 12, 13), pure:
 * how what the API answers today (GET /teams/{id}, /players?team_id, /players/{id}, /competitions/{id}/standings) is put in
 * the maquetas' order. It reads results and lists; it computes no probability and invents nothing - what the profile
 * contract (C-09) will bring is not drawn until it arrives.
 */
import type { MatchSummary, TeamDetail, TeamSummary } from "@/lib/api/v1/types";
import type { PlayerSummary, TableRow } from "@/lib/api/v1/types_center";
import { t } from "@/lib/i18n";
import "@/product/competitions/text";
import { countryFromEnglish } from "@/product/matches/country";

export type ProfileTab = "summary" | "matches" | "squad" | "stats" | "news";
export const PROFILE_TABS: readonly ProfileTab[] = ["summary", "matches", "squad", "stats", "news"];

export function parseTab(raw: unknown): ProfileTab {
  return PROFILE_TABS.includes(raw as ProfileTab) ? (raw as ProfileTab) : "summary";
}

/** A national side: the provider names it after its country (Colombia, country Colombia). */
export function isNation(team: Pick<TeamSummary, "name" | "country">): boolean {
  return (
    Boolean(team.country) && team.name.trim().toLowerCase() === team.country!.trim().toLowerCase()
  );
}

/**
 * A country the provider names in English («Belgium», «Brazil», «World») in the reader's language (AP-T02): «Bélgica»,
 * «Brasil», «Mundo». A name that cannot be matched with certainty stays as the provider wrote it (a group needs a label).
 */
export function countryName(country: string | null | undefined): string | null {
  const name = (country ?? "").trim();
  if (!name) return null;
  if (name.toLowerCase() === "world") return t("competitions.world");
  return countryFromEnglish(name) ?? name;
}

/** A national side is named after its country: in the reader's language too. A club keeps its name. */
export function teamLabel(team: Pick<TeamSummary, "name" | "country">): string {
  return isNation(team) ? (countryFromEnglish(team.name) ?? team.name) : team.name;
}

export type Result = "W" | "D" | "L";

export interface FormItem {
  match: MatchSummary;
  result: Result;
  goalsFor: number;
  goalsAgainst: number;
  home: boolean;
}

/** The team's last results with a score, newest first (at most `n`): won, drawn or lost as the score says. */
export function formOf(recent: readonly MatchSummary[], teamId: number, n = 5): FormItem[] {
  const out: FormItem[] = [];
  for (const m of recent) {
    if (!m.score) continue;
    const home = m.home.id === teamId;
    if (!home && m.away.id !== teamId) continue;
    const gf = home ? m.score.home : m.score.away;
    const ga = home ? m.score.away : m.score.home;
    out.push({
      match: m,
      result: gf > ga ? "W" : gf < ga ? "L" : "D",
      goalsFor: gf,
      goalsAgainst: ga,
      home,
    });
    if (out.length >= n) break;
  }
  return out;
}

/** The competition of the team's league table: the one of its headline record, met in its matches; else its latest. */
export function tableCompetition(detail: TeamDetail): number | null {
  const name = detail.record.data?.competition ?? null;
  const all = [...detail.recent, ...detail.upcoming];
  const hit = name ? all.find((m) => m.competition.name === name) : undefined;
  return (hit ?? detail.recent[0] ?? detail.upcoming[0])?.competition.id ?? null;
}

/** The rows around the team in its table: two above and two below (five), the team's own marked by the caller. */
export function excerpt(rows: readonly TableRow[], teamId: number, around = 2): TableRow[] {
  const i = rows.findIndex((r) => r.team_id === teamId);
  if (i < 0) return [];
  const from = Math.max(0, Math.min(i - around, rows.length - (2 * around + 1)));
  return rows.slice(from, from + 2 * around + 1);
}

const POSITION_ORDER = ["Goalkeeper", "Defender", "Midfielder", "Attacker"] as const;
export type PositionGroup = (typeof POSITION_ORDER)[number] | "Other";

/** The squad by position, in the order a line-up reads; inside each, most minutes first. */
export function squadGroups(
  players: readonly PlayerSummary[],
): { group: PositionGroup; players: PlayerSummary[] }[] {
  const by = new Map<PositionGroup, PlayerSummary[]>();
  for (const p of players) {
    const g = (POSITION_ORDER as readonly string[]).includes(p.position ?? "")
      ? (p.position as PositionGroup)
      : "Other";
    by.set(g, [...(by.get(g) ?? []), p]);
  }
  return [...POSITION_ORDER, "Other" as const]
    .filter((g) => by.has(g))
    .map((g) => ({
      group: g,
      players: [...by.get(g)!].sort(
        (a, b) => (b.minutes ?? 0) - (a.minutes ?? 0) || a.name.localeCompare(b.name),
      ),
    }));
}

/** Whole years between a birth date and now; null without one. */
export function ageOf(birth: string | null | undefined, now: number = Date.now()): number | null {
  if (!birth) return null;
  const b = new Date(`${birth.slice(0, 10)}T12:00:00Z`);
  if (Number.isNaN(b.getTime())) return null;
  const d = new Date(now);
  let years = d.getUTCFullYear() - b.getUTCFullYear();
  if (
    d.getUTCMonth() < b.getUTCMonth() ||
    (d.getUTCMonth() === b.getUTCMonth() && d.getUTCDate() < b.getUTCDate())
  )
    years -= 1;
  return years >= 0 && years < 80 ? years : null;
}
