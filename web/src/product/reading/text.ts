/**
 * The structured reading in the reader's words (plan UX, A9): every fact the API sends is a code with its parameters, and
 * this writes it from the templates of match.facts in Spanish or English. A code without a template is left out - never
 * shown raw - and a parameter that is missing leaves out the part that needs it, so a sentence never carries a gap.
 *
 * The rules of section 26 live in the templates and are tested: no certainty ("seguro", "fijo", "garantizado"), no "value"
 * without a published pick, the probability always labelled when it is the model's own number (uncalibrated).
 */
import { hasKey, t } from "@/lib/i18n";
import { fmtPct, localFixed } from "@/lib/i18n/format";
import type { ReadingFact, ReadingParam } from "@/lib/api/v1/types_reading";
import CODES from "./codes.json";

export const READING_CODES: readonly string[] = CODES;

type P = Record<string, ReadingParam>;

function str(p: P, key: string): string | null {
  const v = p[key];
  return typeof v === "string" && v ? v : null;
}

function int(p: P, key: string): number | null {
  const v = p[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function list(p: P, key: string): string[] {
  const v = p[key];
  return Array.isArray(v)
    ? v.filter((x): x is string => typeof x === "string" && x.length > 0)
    : [];
}

/** A word of a closed list (a zone, a pressure, a block): null for a value the templates do not know. */
function known(key: string): string | null {
  return hasKey(key) ? t(key) : null;
}

function joinAnd(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")}${t("match.facts.and")}${items[items.length - 1]}`;
}

function pct(p: P, key = "probability"): string | null {
  const v = int(p, key);
  return v === null ? null : fmtPct(v, 0);
}

function uncal(p: P): string {
  return p["calibrated"] === false ? t("match.facts.uncalibrated") : "";
}

/** «la victoria de Liverpool» / «el empate»; null when a side's name is missing. */
function outcome(p: P): string | null {
  const o = str(p, "outcome");
  if (o === "draw") return t("match.facts.outcome.draw");
  if (o !== "home" && o !== "away") return null;
  const team = str(p, "team");
  return team ? t(`match.facts.outcome.${o}`, { team }) : null;
}

function places(best: number | null, worst: number | null): string | null {
  if (best === null || worst === null) return null;
  return best === worst
    ? t("match.facts.places.one", { best })
    : t("match.facts.places.range", { best, worst });
}

function total(p: P): string | null {
  const o = str(p, "outcome");
  const line = str(p, "line") ?? "2.5";
  if (o !== "over" && o !== "under") return null;
  return t(`match.facts.total.${o}`, { line: localFixed(Number(line), 1) });
}

function tieAhead(n: number): string {
  if (n >= 2) return t("match.facts.tie.ahead_many", { count: n });
  if (n === 1) return t("match.facts.tie.ahead_one");
  if (n === 0) return t("match.facts.tie.ahead_zero");
  return n === -1
    ? t("match.facts.tie.ahead_lose_one")
    : t("match.facts.tie.ahead_lose_many", { count: -n });
}

function tieLevel(n: number): string {
  if (n === 0) return t("match.facts.tie.level_zero");
  if (n > 0)
    return n === 1
      ? t("match.facts.tie.level_win_one")
      : t("match.facts.tie.level_win_many", { count: n });
  return n === -1
    ? t("match.facts.tie.level_lose_one")
    : t("match.facts.tie.level_lose_many", { count: -n });
}

function letters(sequence: string): string {
  return [...sequence]
    .map((c) => (c === "W" || c === "D" || c === "L" ? t(`match.facts.formLetters.${c}`) : ""))
    .join("");
}

function writers(): Record<string, (p: P) => string | null> {
  return {
    match_intro: (p) => {
      const competition = str(p, "competition");
      if (!competition) return null;
      const round = str(p, "round");
      const base = round
        ? t("match.facts.match_intro.round", { competition, round })
        : t("match.facts.match_intro.plain", { competition });
      return p["neutral"] === true ? base + t("match.facts.match_intro.neutral") : base;
    },
    match_kind: (p) => {
      const kind = str(p, "kind");
      return kind && ["final", "second_leg", "knockout", "derby", "friendly"].includes(kind)
        ? t(`match.facts.match_kind.${kind}`)
        : null;
    },
    expected_result: (p) => {
      const o = outcome(p);
      const v = pct(p);
      return o && v
        ? t("match.facts.expected_result", { outcome: o, pct: v, uncal: uncal(p) })
        : null;
    },
    forecast_missing: (p) => missing(p),
    no_forecast: (p) => missing(p),
    stakes_zone: (p) => {
      const team = str(p, "team");
      const zone = known(`match.facts.zone.${str(p, "zone") ?? ""}`);
      if (!team || !zone) return null;
      const rank = int(p, "rank");
      return t("match.facts.stakes_zone", {
        team,
        rank: rank === null ? "" : t("match.facts.rank", { rank }),
        zone,
      });
    },
    stakes_gap_up: (p) => gap(p, "stakes_gap_up"),
    stakes_gap_down: (p) => gap(p, "stakes_gap_down"),
    stakes_pressure: (p) => {
      const team = str(p, "team");
      const key = `match.facts.pressure.${str(p, "pressure") ?? ""}`;
      return team && hasKey(key) ? t(key, { team }) : null;
    },
    first_leg: (p) => {
      const h = int(p, "home_goals");
      const a = int(p, "away_goals");
      return h === null || a === null
        ? null
        : t("match.facts.first_leg", { home_goals: h, away_goals: a });
    },
    tie_outlook: (p) => {
      const ahead = int(p, "ahead_from");
      const level = int(p, "level_at");
      const home = str(p, "home");
      if (ahead === null || level === null || !home) return null;
      return t("match.facts.tie_outlook", { home, ahead: tieAhead(ahead), level: tieLevel(level) });
    },
    table_after: (p) => {
      const result = str(p, "result");
      const home = str(p, "home");
      const away = str(p, "away");
      const hp = int(p, "home_points");
      const ap = int(p, "away_points");
      const hPlaces = places(int(p, "home_best"), int(p, "home_worst"));
      const aPlaces = places(int(p, "away_best"), int(p, "away_worst"));
      const key = `match.facts.table_after.${result ?? ""}`;
      if (!hasKey(key) || !home || !away || hp === null || ap === null || !hPlaces || !aPlaces)
        return null;
      return t(key, {
        home,
        away,
        home_points: hp,
        away_points: ap,
        home_places: hPlaces,
        away_places: aPlaces,
      });
    },
    rest_days: (p) => {
      const team = str(p, "team");
      const d = int(p, "days");
      if (!team || d === null) return null;
      const days = t(
        p["at_most"] === true ? "match.facts.days.at_most" : "match.facts.days.exact",
        {
          days: localFixed(d, d % 1 === 0 ? 0 : 1),
        },
      );
      const matches = int(p, "matches_14d");
      return matches === null
        ? t("match.facts.rest_days", { team, days })
        : t("match.facts.rest_days_matches", { team, days, matches });
    },
    next_match: (p) => {
      const team = str(p, "team");
      const d = int(p, "days");
      if (!team || d === null) return null;
      const days = localFixed(d, d % 1 === 0 ? 0 : 1);
      const competition = str(p, "competition");
      return competition
        ? t("match.facts.next_match_comp", { team, days, competition })
        : t("match.facts.next_match", { team, days });
    },
    form: (p) => {
      const team = str(p, "team");
      const sequence = str(p, "sequence");
      const n = int(p, "n");
      if (!team || !sequence || n === null) return null;
      return t("match.facts.form", {
        team,
        sequence: letters(sequence),
        n,
        ppg: localFixed(int(p, "ppg") ?? 0, 2),
        gf: localFixed(int(p, "goals_for") ?? 0, 1),
        ga: localFixed(int(p, "goals_against") ?? 0, 1),
      });
    },
    venue_record: (p) => {
      const team = str(p, "team");
      const side = str(p, "side");
      const n = int(p, "n");
      if (!team || (side !== "home" && side !== "away") || n === null) return null;
      return t(`match.facts.venue_record.${side}`, {
        team,
        n,
        w: int(p, "wins") ?? 0,
        d: int(p, "draws") ?? 0,
        l: int(p, "losses") ?? 0,
      });
    },
    xg: (p) => {
      const team = str(p, "team");
      const xf = int(p, "xg_for");
      const xa = int(p, "xg_against");
      if (!team || xf === null || xa === null) return null;
      const n = int(p, "n");
      const vars = { team, xg_for: localFixed(xf, 2), xg_against: localFixed(xa, 2) };
      return n === null ? t("match.facts.xg_plain", vars) : t("match.facts.xg", { ...vars, n });
    },
    streak_unbeaten: (p) => streak(p, "streak_unbeaten"),
    streak_winless: (p) => streak(p, "streak_winless"),
    h2h: (p) => {
      const n = int(p, "n");
      const home = str(p, "home");
      const away = str(p, "away");
      if (n === null || !home || !away) return null;
      return t("match.facts.h2h", {
        n,
        home,
        away,
        home_wins: int(p, "home_wins") ?? 0,
        draws: int(p, "draws") ?? 0,
        away_wins: int(p, "away_wins") ?? 0,
        n_effective: localFixed(int(p, "n_effective") ?? 0, 1),
      });
    },
    top_scorer: (p) => {
      const team = str(p, "team");
      const player = str(p, "player");
      const goals = int(p, "goals");
      if (!team || !player || goals === null) return null;
      const minutes = int(p, "minutes");
      return minutes === null
        ? t("match.facts.top_scorer", { team, player, goals })
        : t("match.facts.top_scorer_minutes", { team, player, goals, minutes });
    },
    key_absences: (p) => {
      const team = str(p, "team");
      const players = list(p, "players");
      const count = int(p, "count") ?? players.length;
      if (!team || players.length === 0) return null;
      const more = count - players.length;
      return more > 0
        ? t("match.facts.key_absences_more", { team, players: joinAnd(players), more })
        : t("match.facts.key_absences", { team, players: joinAnd(players) });
    },
    market_unpriced: () => t("match.facts.market_unpriced"),
    market_favourite: (p) => {
      const o = outcome(p);
      const v = pct(p);
      if (!o || !v) return null;
      const books = int(p, "bookmakers");
      return books === null
        ? t("match.facts.market_favourite", { outcome: o, pct: v })
        : t("match.facts.market_favourite_books", { outcome: o, pct: v, books });
    },
    market_moved: (p) => {
      const o = outcome(p);
      const opening = pct(p, "opening");
      const now = pct(p, "now");
      return o && opening && now
        ? t("match.facts.market_moved", { outcome: o, opening, now })
        : null;
    },
    market_total: (p) => {
      const tt = total(p);
      const v = pct(p);
      return tt && v ? t("match.facts.market_total", { total: tt, pct: v }) : null;
    },
    no_context_yet: () => t("match.facts.no_context_yet"),
    lineups_unconfirmed: () => t("match.facts.lineups_unconfirmed"),
    short_rest: (p) => withTeam(p, "match.facts.short_rest"),
    rest_disadvantage: (p) => withTeam(p, "match.facts.rest_disadvantage"),
    contradictory_news: (p) => counted(p, "match.facts.contradictory_news"),
    rumours: (p) => counted(p, "match.facts.rumours"),
    no_external_info: () => t("match.facts.no_external_info"),
    h2h_weak: (p) => {
      const n = int(p, "n");
      if (n === null) return null;
      return t("match.facts.h2h_weak", {
        n,
        n_effective: localFixed(int(p, "n_effective") ?? 0, 1),
      });
    },
    data_not_fit: () => t("match.facts.data_not_fit"),
    not_checked: (p) => {
      const blocks = list(p, "blocks").flatMap((b) => known(`match.facts.blocks.${b}`) ?? []);
      return blocks.length ? t("match.facts.not_checked", { blocks: joinAnd(blocks) }) : null;
    },
    uncalibrated: (p) => {
      const markets = list(p, "markets").flatMap((m) => known(`match.facts.markets.${m}`) ?? []);
      return markets.length
        ? t("match.facts.uncalibrated_markets", { markets: joinAnd(markets) })
        : null;
    },
    none_found: () => t("match.facts.none_found"),
    description_only: () => t("match.facts.description_only"),
    likely: (p) => {
      const market = str(p, "market");
      const v = pct(p);
      if (!v) return null;
      if (market === "1X2") {
        const o = outcome(p);
        return o ? t("match.facts.likely.1X2", { outcome: o, pct: v, uncal: uncal(p) }) : null;
      }
      if (market === "OU") {
        const tt = total(p);
        return tt ? t("match.facts.likely.OU", { total: tt, pct: v, uncal: uncal(p) }) : null;
      }
      if (market === "BTTS") {
        const o = str(p, "outcome");
        return o === "yes" || o === "no"
          ? t("match.facts.likely.BTTS", {
              btts: t(`match.facts.btts.${o}`),
              pct: v,
              uncal: uncal(p),
            })
          : null;
      }
      return null;
    },
  };
}

function missing(p: P): string | null {
  const reason = str(p, "reason");
  return reason && ["data_not_fit", "quarantined", "no_forecast_yet", "hidden"].includes(reason)
    ? t(`match.facts.missing.${reason}`)
    : null;
}

function gap(p: P, code: "stakes_gap_up" | "stakes_gap_down"): string | null {
  const team = str(p, "team");
  const zone = known(`match.facts.zone.${str(p, "zone") ?? ""}`);
  const g = int(p, "gap");
  return team && zone && g !== null ? t(`match.facts.${code}`, { team, count: g, zone }) : null;
}

function streak(p: P, code: "streak_unbeaten" | "streak_winless"): string | null {
  const team = str(p, "team");
  const n = int(p, "n");
  return team && n !== null ? t(`match.facts.${code}`, { team, n }) : null;
}

function withTeam(p: P, key: string): string | null {
  const team = str(p, "team");
  return team ? t(key, { team }) : null;
}

function counted(p: P, key: string): string | null {
  const count = int(p, "count");
  return count === null || count <= 0 ? null : t(key, { count });
}

let cached: Record<string, (p: P) => string | null> | null = null;

/** The fact in the reader's words, or null: a code this page does not know is left out, never shown raw. */
export function factText(fact: ReadingFact): string | null {
  cached ??= writers();
  const write = cached[fact.code];
  if (!write) return null;
  const text = write(fact.params);
  return text && text.trim() ? text : null;
}

/** The codes this page writes (the parity test holds them equal to codes.json and to the API's). */
export function writtenCodes(): string[] {
  cached ??= writers();
  return Object.keys(cached);
}
