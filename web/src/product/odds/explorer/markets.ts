/**
 * What the explorer knows of a tax-v3 market key (backend `fbi.odds.book_taxonomy`): its parts, how its selections read
 * (its shape), whether it is one of the five markets of Mi Parlay, where it sits among the others and its name in the
 * reader's language. Pure: no React here.
 *
 * A key is `<domain>.<market>[.<period>][.<interval>][.<home|away>]` ("corners.total", "goals.total.home",
 * "result.1x2.m0_15"); the API lists a market without its period (`OddsMarketInfo.periods` carries them), and the explorer
 * copes with a period, an interval or a team left in the key. The words live in the `explorer` namespace (`markets` for the
 * five classic ones: one name per market across the product); a key without a name reads «Otro mercado», never the key.
 */
import { t, translateOr } from "@/lib/i18n";
import { marketName, type MarketKey } from "@/product/shared/markets";
import type { OddsMarketInfo } from "./model";

export interface MarketKeyParts {
  /** The market without period, interval and team: "corners.total". */
  base: string;
  /** An interval named in the key ("m0_15" -> [0, 15]). */
  minutes: readonly [number, number] | null;
  /** A team named in the key. */
  team: "home" | "away" | null;
}

const INTERVAL = /^m(\d{1,3})_(\d{1,3})$/;

export function parseMarketKey(key: string): MarketKeyParts {
  const parts = key.split(".");
  let minutes: [number, number] | null = null;
  let team: "home" | "away" | null = null;
  for (const part of parts.slice(2)) {
    const m = INTERVAL.exec(part);
    if (m) minutes = [Number(m[1]), Number(m[2])];
    else if (part === "home" || part === "away") team = part;
  }
  return { base: parts.slice(0, 2).join("."), minutes, team };
}

/**
 * How a market's selections read, after the tax-v3 readers: a closed vocabulary (plain), a word and a line (line: over /
 * under), an Asian handicap (each side at its own signed line), a European handicap (three ways at the home handicap), a
 * race to N, an exact score, half-time/full-time, result + total, total + both score, an exact count, bands, a player, a
 * player reaching N.
 */
export type Shape =
  | "plain"
  | "line"
  | "ah"
  | "eh"
  | "race"
  | "exact_score"
  | "ht_ft"
  | "result_total"
  | "total_btts"
  | "count"
  | "range"
  | "player"
  | "player_count";

/** `OddsMarketInfo.kind`, when it names a tax-v3 reader (or the handicap itself). */
const KIND_SHAPE: Readonly<Record<string, Shape>> = {
  plain: "plain",
  line: "line",
  signed_line: "ah",
  signed_line_3way: "eh",
  asian_handicap: "ah",
  european_handicap: "eh",
  race: "race",
  exact_score: "exact_score",
  ht_ft: "ht_ft",
  result_total: "result_total",
  total_btts: "total_btts",
  count: "count",
  range: "range",
  player: "player",
  player_count: "player_count",
};

const LINE_BASES = new Set([
  "goals.total",
  "goals.goal_line",
  "corners.total",
  "corners.total_3way",
  "corners.multicorners",
  "cards.total",
  "shots.on_target",
  "shots.total",
  "offsides.total",
  "tackles.total",
]);
const PLAYER_COUNT_BASES = new Set([
  "player.shots",
  "player.fouls",
  "player.shots_on_target",
  "keeper.saves",
]);

function shapeOfBase(base: string): Shape {
  if (base.endsWith(".asian_handicap")) return "ah";
  if (base.endsWith(".european_handicap")) return "eh";
  if (base.endsWith(".correct_score")) return "exact_score";
  if (base.endsWith(".exact_total")) return "count";
  if (base.endsWith(".total_bands")) return "range";
  if (base === "corners.race") return "race";
  if (base === "goals.result_total") return "result_total";
  if (base === "goals.total_btts") return "total_btts";
  if (base === "halves.ht_ft") return "ht_ft";
  if (LINE_BASES.has(base)) return "line";
  if (PLAYER_COUNT_BASES.has(base)) return "player_count";
  if (base.startsWith("player.")) return "player";
  return "plain";
}

export function shapeOf(info: Pick<OddsMarketInfo, "key" | "kind">): Shape {
  const { base } = parseMarketKey(info.key);
  const byKind = KIND_SHAPE[info.kind];
  // The race is read by the «line» reader («Home 5»: the home team reaches 5 first): its own words.
  if (byKind === "line" && base === "corners.race") return "race";
  return byKind ?? shapeOfBase(base);
}

/** A handicap of any family: what the «Hándicaps» view gathers. */
export function isHandicap(info: Pick<OddsMarketInfo, "key" | "kind">): boolean {
  const shape = shapeOf(info);
  return shape === "ah" || shape === "eh";
}

/** The five markets of Mi Parlay, by their tax-v3 base. */
const CLASSIC: Readonly<Record<string, MarketKey>> = {
  "result.1x2": "1X2",
  "goals.total": "OU",
  "goals.btts": "BTTS",
  "result.asian_handicap": "AH",
  "result.double_chance": "DC",
};

/** The order «Principales» opens with: today's five, as the Cuotas tabs had them. */
const CLASSIC_ORDER: readonly string[] = [
  "result.1x2",
  "goals.total",
  "goals.btts",
  "result.asian_handicap",
  "result.double_chance",
];

/** One of the five classic markets, for the whole match (any period): «Principales» lists it. */
export function isClassic(info: Pick<OddsMarketInfo, "key" | "subject">): boolean {
  const p = parseMarketKey(info.key);
  return p.base in CLASSIC && info.subject === "match" && p.team === null && p.minutes === null;
}

/**
 * The slip's market key of a price, or null: only the five classic markets, for the whole match and the full time, go in a
 * parlay (the server's `parlay_ok` decides the rest).
 */
export function classicMarket(
  info: Pick<OddsMarketInfo, "key" | "subject" | "parlay">,
  period: string,
): MarketKey | null {
  if (!info.parlay || period !== "FT" || !isClassic(info)) return null;
  return CLASSIC[parseMarketKey(info.key).base] ?? null;
}

/**
 * Every market of tax-v3 in the order the explorer lists them (the taxonomy's own order): the classic five first in
 * «Principales», then the rest of each family.
 */
export const MARKET_ORDER: readonly string[] = [
  "result.1x2",
  "result.draw_no_bet",
  "result.asian_handicap",
  "result.european_handicap",
  "result.double_chance",
  "advance.to_qualify",
  "goals.total",
  "goals.btts",
  "goals.correct_score",
  "goals.odd_even",
  "goals.result_btts",
  "goals.result_total",
  "goals.clean_sheet",
  "goals.win_to_nil",
  "goals.exact_total",
  "goals.team_scores",
  "goals.winning_margin",
  "goals.total_btts",
  "goals.goal_line",
  "goals.score_draw",
  "goals.total_bands",
  "goals.first_team_to_score",
  "goals.last_team_to_score",
  "halves.ht_ft",
  "halves.highest_scoring",
  "halves.win_both",
  "halves.win_either",
  "halves.score_both",
  "halves.btts_both",
  "halves.goal_both",
  "corners.total",
  "corners.1x2",
  "corners.asian_handicap",
  "corners.total_3way",
  "corners.european_handicap",
  "corners.total_bands",
  "corners.odd_even",
  "corners.double_chance",
  "corners.multicorners",
  "corners.race",
  "cards.total",
  "cards.asian_handicap",
  "cards.european_handicap",
  "cards.first_card",
  "shots.on_target",
  "shots.total",
  "shots.on_target_1x2",
  "shots.1x2",
  "offsides.total",
  "tackles.total",
  "keeper.saves",
  "player.anytime_scorer",
  "player.first_scorer",
  "player.last_scorer",
  "player.score_or_assist",
  "player.shots",
  "player.fouls",
  "player.shots_on_target",
  "player.header_goal",
  "player.outside_box_goal",
  "special.own_goal",
  "special.first_goal_method",
  "special.penalty_scored",
  "special.penalty_missed",
  "special.win_from_behind",
  "special.decided_by_penalties",
  "special.decided_in_extra_time",
  "special.method_of_victory",
];

const SUBJECT_ORDER: Readonly<Record<string, number>> = {
  match: 0,
  home: 1,
  away: 2,
  player: 3,
  keeper: 4,
};

/** The subject a market is about: the key's team, else the API's. */
export function subjectOf(info: Pick<OddsMarketInfo, "key" | "subject">): string {
  return parseMarketKey(info.key).team ?? info.subject;
}

/** Sorts markets: the classic five first where `classicFirst`, then the taxonomy's order, the match before each team. */
export function compareMarkets(
  a: Pick<OddsMarketInfo, "key" | "subject">,
  b: Pick<OddsMarketInfo, "key" | "subject">,
  classicFirst = false,
): number {
  const rank = (info: Pick<OddsMarketInfo, "key" | "subject">): number[] => {
    const p = parseMarketKey(info.key);
    const classic = classicFirst && isClassic(info) ? CLASSIC_ORDER.indexOf(p.base) : -1;
    const order = MARKET_ORDER.indexOf(p.base);
    return [
      classic >= 0 ? classic : CLASSIC_ORDER.length,
      order >= 0 ? order : MARKET_ORDER.length,
      SUBJECT_ORDER[subjectOf(info)] ?? 9,
      p.minutes ? p.minutes[1] : -1,
    ];
  };
  const ra = rank(a);
  const rb = rank(b);
  for (let i = 0; i < ra.length; i++) {
    const d = (ra[i] ?? 0) - (rb[i] ?? 0);
    if (d !== 0) return d;
  }
  return a.key.localeCompare(b.key);
}

function suffixes(info: Pick<OddsMarketInfo, "key" | "subject">): string {
  const p = parseMarketKey(info.key);
  const subject = subjectOf(info);
  let text = "";
  if (p.minutes) {
    text += ` · ${t("explorer.interval", { from: p.minutes[0], to: p.minutes[1] })}`;
  }
  if (subject === "home" || subject === "away") text += ` · ${t(`explorer.subject.${subject}`)}`;
  return text;
}

/** The market's one name: «Hándicap asiático», «Córners: más/menos · Local», «Goleador en cualquier momento». */
export function marketTitle(info: Pick<OddsMarketInfo, "key" | "subject">): string {
  const { base } = parseMarketKey(info.key);
  const classic = CLASSIC[base];
  const name = classic
    ? marketName(classic)
    : translateOr(`explorer.market.${base}`, t("explorer.marketUnknown"));
  return `${name}${suffixes(info)}`;
}

/**
 * The name on its chip: inside its own family's tab the family is not repeated («Más/menos» under Córners); in a view that
 * mixes families («Hándicaps», «Más») the whole name.
 */
export function chipTitle(info: Pick<OddsMarketInfo, "key" | "subject">, own: boolean): string {
  const { base } = parseMarketKey(info.key);
  const chip = `explorer.chip.${base}`;
  if (!own) return marketTitle(info);
  const name = translateOr(chip, "");
  return name ? `${name}${suffixes(info)}` : marketTitle(info);
}

export function familyName(family: string): string {
  return translateOr(`explorer.family.${family}`, t("explorer.family.other"));
}

const PERIODS = ["FT", "1H", "2H", "INTERVAL"] as const;

/** The periods in the order the switch shows them: the match, the first half, the second, then the rest. */
export function comparePeriods(a: string, b: string): number {
  const ia = (PERIODS as readonly string[]).indexOf(a);
  const ib = (PERIODS as readonly string[]).indexOf(b);
  return (ia < 0 ? PERIODS.length : ia) - (ib < 0 ? PERIODS.length : ib) || a.localeCompare(b);
}

export function periodName(period: string): string {
  return translateOr(`explorer.period.${period}`, period);
}
