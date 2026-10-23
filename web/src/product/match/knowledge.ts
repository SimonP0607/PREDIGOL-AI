/**
 * POSTPARTIDO in words (plan F7): what the block shows for a given answer of the API - how the score went, what the market
 * expected against what happened, the best of the match, the formations and the changes - and how far all of it can be
 * trusted. Pure: no React, no fetching.
 *
 * Everything here is a FACT of a match that is over. Nothing turns it into a pick, a price to take or a recommendation: the
 * decision layer's picks and the post-mortems are in the row as stored, and that is the Admin Console's preview alone.
 */
import { t, translateOr } from "@/lib/i18n";
import { fmtInt, fmtOdds, fmtPct, toNumber } from "@/lib/i18n/format";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  AfterMatch,
  KnowledgeCompleteness,
  KnowledgeEventLine,
  KnowledgeResult,
  KnowledgeSide,
  KnowledgeStoredBuild,
  KnowledgeStory,
  MatchKnowledge,
} from "@/lib/api/v1/types_knowledge";
import { marketTitle, selectionPhrase, type Sides } from "./intelligence";
import { minuteText } from "./model";

/** The block's anchor. */
export const KNOWLEDGE_ID = "predigol-postmatch";

/** The 90 minutes the markets settle on, and the story is told over. */
const REGULATION = 90;

// ── what the block shows ────────────────────────────────────────────────────

/** The query as the block receives it, apart from React Query so that the block can be rendered from a fixture. */
export type KnowledgeLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry?: (() => void) | undefined }
  | { status: "success"; envelope: Envelope<MatchKnowledge | null> };

export type KnowledgeScreen =
  /** A user is not told about a summary that is not there: not allowed yet, not loaded, not loadable, nothing to tell. */
  | { kind: "nothing" }
  | { kind: "loading" }
  | { kind: "error"; error: unknown; retry?: (() => void) | undefined }
  /** The API answered, and PrediGol has no summary of this match. `data` carries what the preview adds. */
  | { kind: "none"; code: string | null; data: MatchKnowledge | null }
  | { kind: "knowledge"; data: MatchKnowledge; after: AfterMatch };

/**
 * The only reason a user is told: a match that just ended and is still being settled gets its summary within hours. The other
 * reasons are a match that never gets one (a competition PrediGol does not follow) or a gap that closes by itself, and a user
 * is not shown a gap on every old match.
 */
const REASONS_FOR_USERS: ReadonlySet<string> = new Set(["not_settled_yet"]);

/**
 * What the block shows. A user sees it only once the API says so (the owner decides when: `FBI_KNOWLEDGE_USERS`), and never a
 * spinner, an error or a gap for something that may not be shown to them at all. The Admin Console's preview sees every
 * state, so that a missing summary is a thing it can read.
 */
export function knowledgeScreen(load: KnowledgeLoad, preview: boolean): KnowledgeScreen {
  if (load.status === "pending") return preview ? { kind: "loading" } : { kind: "nothing" };
  if (load.status === "error") {
    return preview ? { kind: "error", error: load.error, retry: load.retry } : { kind: "nothing" };
  }
  const { envelope } = load;
  const data = envelope.data;
  if (envelope.status !== "ok" || !data) {
    return preview ? { kind: "none", code: null, data: null } : { kind: "nothing" };
  }
  const after = data.knowledge.status === "ok" ? data.knowledge.data : null;
  if (!after) {
    const code = data.knowledge.code ?? null;
    if (!preview && (code === null || !REASONS_FOR_USERS.has(code))) return { kind: "nothing" };
    return { kind: "none", code, data };
  }
  if (!preview && !hasContent(after)) return { kind: "nothing" };
  return { kind: "knowledge", data, after };
}

/** Why a match has no summary, in the reader's language (the API's own reason is English and technical). */
export function noKnowledgeText(code: string | null | undefined): string {
  return code
    ? translateOr(`match.knowledge.reason.${code}`, t("match.note.notAvailable"))
    : t("match.note.notAvailable");
}

/** Is there anything to tell a reader: a section with something in it, or a mark worth a tag. */
export function hasContent(after: AfterMatch): boolean {
  const result = after.result.data;
  return (
    headlines(after).length > 0 ||
    (result !== null && tieText(result) !== null) ||
    storyOf(after) !== null ||
    storyUntold(after) ||
    marketReads(after).length > 0 ||
    bestPlayers(after) !== null ||
    lineups(after) !== null
  );
}

// ── the result's marks ──────────────────────────────────────────────────────

export type HeadlineKey =
  "extraTime" | "penalties" | "comeback" | "levelled" | "neutral" | "corrected";

export interface Headline {
  key: HeadlineKey;
  /** The side a comeback or a levelled game is about. */
  side?: KnowledgeSide;
}

/** Who came back: the side that won after being behind, or the side that drew after being behind. */
export function comebackOf(
  result: Pick<KnowledgeResult, "outcome">,
  story: Pick<KnowledgeStory, "ahead">,
): { kind: "comeback" | "levelled"; side: KnowledgeSide } | null {
  const { ahead } = story;
  if (result.outcome === "Home") return ahead.away ? { kind: "comeback", side: "home" } : null;
  if (result.outcome === "Away") return ahead.home ? { kind: "comeback", side: "away" } : null;
  // A draw: the side that was never ahead and still got level came back; if both were ahead nobody did.
  if (ahead.home && !ahead.away) return { kind: "levelled", side: "away" };
  if (ahead.away && !ahead.home) return { kind: "levelled", side: "home" };
  return null;
}

/** The marks the result carries beyond its score, in the order the block shows them. */
export function headlines(after: AfterMatch): Headline[] {
  const result = after.result.data;
  if (!result) return [];
  const out: Headline[] = [];
  if (result.decided_by === "penalties") out.push({ key: "penalties" });
  else if (result.decided_by === "extra_time") out.push({ key: "extraTime" });
  const story = storyOf(after);
  const turn = story ? comebackOf(result, story) : null;
  if (turn) out.push({ key: turn.kind, side: turn.side });
  if (result.neutral) out.push({ key: "neutral" });
  if (result.corrected) out.push({ key: "corrected" });
  return out;
}

export function headlineText(headline: Headline, sides: Sides): string {
  const team = headline.side ? sides[headline.side] : "";
  return t(`match.knowledge.tag.${headline.key}`, { team });
}

/** "Global 3–2" for the leg that closed a tie, unless the provider's winner disagrees with the aggregate (not to be quoted). */
export function tieText(result: Pick<KnowledgeResult, "tie">): string | null {
  const tie = result.tie;
  if (!tie || !tie.aggregate || tie.contradicted) return null;
  return t("match.tie.global", { score: `${tie.aggregate[0]}–${tie.aggregate[1]}` });
}

// ── the story of the score ──────────────────────────────────────────────────

export function storyOf(after: AfterMatch): KnowledgeStory | null {
  return after.tactics.data?.story ?? null;
}

/** The events exist but do not give the score: the story is not told, and the block says so instead of leaving a gap. */
export function storyUntold(after: AfterMatch): boolean {
  return storyOf(after) === null && after.quality.events_give_the_score === false;
}

export type LeadState = "home" | "level" | "away";

export interface LeadSegment {
  from: number;
  to: number;
  state: LeadState;
}

export interface LeadMinutes {
  home_ahead: number;
  level: number;
  away_ahead: number;
}

type GoalLine = Pick<KnowledgeEventLine, "period" | "minute" | "side">;

/** The minute a goal is drawn at: stoppage time counts as the 90th, as in the API's own count. */
export function goalMinute(goal: Pick<KnowledgeEventLine, "minute">): number {
  return Math.min(Math.max(goal.minute, 0), REGULATION);
}

/**
 * Who led, minute by minute, over the 90 minutes - the same count the API makes (`story.minutes`), drawn in the order it
 * happened. The goals are the list of the events layer, in the order they happened. Extra time and the shoot-out are not
 * part of the story.
 */
export function leadTimeline(goals: readonly GoalLine[]): LeadSegment[] {
  const out: LeadSegment[] = [];
  let lead = 0;
  let prev = 0;
  const state = (): LeadState => (lead > 0 ? "home" : lead < 0 ? "away" : "level");
  const close = (to: number): void => {
    if (to <= prev) return;
    const last = out[out.length - 1];
    if (last && last.state === state()) last.to = to;
    else out.push({ from: prev, to, state: state() });
  };
  for (const g of goals) {
    if ((g.period !== "1H" && g.period !== "2H") || (g.side !== "home" && g.side !== "away")) {
      continue;
    }
    const at = goalMinute(g);
    close(at);
    prev = Math.max(prev, at);
    lead += g.side === "home" ? 1 : -1;
  }
  close(REGULATION);
  return out;
}

export function leadMinutes(segments: readonly LeadSegment[]): LeadMinutes {
  const total: LeadMinutes = { home_ahead: 0, level: 0, away_ahead: 0 };
  for (const s of segments) {
    const span = s.to - s.from;
    if (s.state === "home") total.home_ahead += span;
    else if (s.state === "away") total.away_ahead += span;
    else total.level += span;
  }
  return total;
}

export function sameMinutes(a: LeadMinutes, b: LeadMinutes): boolean {
  return a.home_ahead === b.home_ahead && a.level === b.level && a.away_ahead === b.away_ahead;
}

/** A moment of the 90 minutes as the share (0-100) of the track, to two places. */
export function trackPercent(minute: number): number {
  const share = (Math.min(Math.max(minute, 0), REGULATION) / REGULATION) * 100;
  return Math.round(share * 100) / 100;
}

export interface StoryDrawing {
  /** Time-ordered segments, or the totals as three blocks when the goals do not add up to the API's count. */
  kind: "timeline" | "totals";
  segments: LeadSegment[];
  /** The goals of the 90 minutes, to mark on the track (only with a timeline). */
  ticks: { minute: number; side: KnowledgeSide }[];
  minutes: LeadMinutes;
}

/**
 * What to draw for the story. The numbers are the API's. The order is drawn from the goals, and only when they give back
 * exactly the API's count: otherwise the totals are drawn as three blocks, because a picture must never say more than the
 * numbers beside it.
 */
export function storyDrawing(
  story: Pick<KnowledgeStory, "minutes">,
  goals: readonly GoalLine[],
): StoryDrawing {
  const minutes: LeadMinutes = story.minutes;
  const segments = leadTimeline(goals);
  if (sameMinutes(leadMinutes(segments), minutes)) {
    const ticks = goals.flatMap((g) =>
      (g.period === "1H" || g.period === "2H") && (g.side === "home" || g.side === "away")
        ? [{ minute: goalMinute(g), side: g.side }]
        : [],
    );
    return { kind: "timeline", segments, ticks, minutes };
  }
  const blocks: LeadSegment[] = [];
  let from = 0;
  for (const [state, span] of [
    ["home", minutes.home_ahead],
    ["level", minutes.level],
    ["away", minutes.away_ahead],
  ] as const) {
    if (span > 0) {
      blocks.push({ from, to: from + span, state });
      from += span;
    }
  }
  return { kind: "totals", segments: blocks, ticks: [], minutes };
}

/** The key under the bar: who led for how long. A state that never held is not listed. */
export function storyLegend(
  minutes: LeadMinutes,
  sides: Sides,
): { state: LeadState; text: string; span: string }[] {
  const items: { state: LeadState; n: number; text: string }[] = [
    {
      state: "home",
      n: minutes.home_ahead,
      text: t("match.knowledge.story.ahead", { team: sides.home }),
    },
    { state: "level", n: minutes.level, text: t("match.knowledge.story.level") },
    {
      state: "away",
      n: minutes.away_ahead,
      text: t("match.knowledge.story.ahead", { team: sides.away }),
    },
  ];
  return items
    .filter((i) => i.n > 0)
    .map((i) => ({
      state: i.state,
      text: i.text,
      span: t("match.knowledge.minutes.short", { n: i.n }),
    }));
}

/** "ganando por 1", "perdiendo por 2", "empatando": the lead of a side at a moment. Null when the events do not give the score. */
export function leadText(lead: number | null | undefined): string | null {
  if (lead === null || lead === undefined || !Number.isFinite(lead)) return null;
  if (lead > 0) return t("match.knowledge.lead.ahead", { n: lead });
  if (lead < 0) return t("match.knowledge.lead.behind", { n: Math.abs(lead) });
  return t("match.knowledge.lead.level");
}

export interface StoryFact {
  key: "firstGoal" | "lastGoal" | "leadChanges" | "firstDismissal" | "noGoals";
  label: string;
  value: string;
}

/** The facts under the bar: the first goal, the last, how often the lead changed, and the first man sent off. */
export function storyFacts(story: KnowledgeStory, sides: Sides): StoryFact[] {
  const facts: StoryFact[] = [];
  const first = story.first_goal;
  if (first) {
    facts.push({
      key: "firstGoal",
      label: t("match.knowledge.story.firstGoal"),
      value: t("match.knowledge.teamMinute", {
        team: sides[first.side],
        minute: minuteText(first.minute, null),
      }),
    });
    const last = story.last_goal_minute;
    if (last !== null && last !== first.minute) {
      facts.push({
        key: "lastGoal",
        label: t("match.knowledge.story.lastGoal"),
        value: minuteText(last, null),
      });
    }
    facts.push({
      key: "leadChanges",
      label: t("match.knowledge.story.leadChanges"),
      value: fmtInt(story.lead_changes),
    });
  } else {
    facts.push({
      key: "noGoals",
      label: t("match.knowledge.story.goals"),
      value: t("match.knowledge.story.noGoals"),
    });
  }
  const sent = story.first_dismissal;
  if (sent) {
    const team = sides[sent.side];
    const minute = minuteText(sent.minute, null);
    const state = leadText(sent.lead);
    facts.push({
      key: "firstDismissal",
      label: t("match.knowledge.story.firstDismissal"),
      value: state
        ? t("match.knowledge.teamMinuteState", { team, minute, state })
        : t("match.knowledge.teamMinute", { team, minute }),
    });
  }
  return facts;
}

// ── the market ──────────────────────────────────────────────────────────────

/** The markets the block reads, in the order of the board. Handicaps are for the Markets tab. */
export const MARKET_KEYS = ["1X2", "OU", "BTTS"] as const;

const SELECTION_ORDER: Readonly<Record<string, readonly string[]>> = {
  "1X2": ["Home", "Draw", "Away"],
  OU: ["Over", "Under"],
  BTTS: ["Yes", "No"],
};

export interface MarketRow {
  selection: string;
  /** The consensus probability at the market's first reading of the week; null when it was not quoted that week. */
  open: number | null;
  /** At its last reading before kick-off. */
  close: number;
  happened: boolean;
}

export interface MarketRead {
  market: string;
  line: number | null;
  rows: MarketRow[];
  /** The selection that came in; null when the result does not say one (a line that was pushed or settled in halves). */
  happened: string | null;
  /** The total landed on the line itself: no selection won. */
  pushed: boolean;
  books: number | null;
  minutesToKickoff: number | null;
}

/** Which selection of a market the 90 minutes settled on. A whole line that the total landed on is pushed, a quarter line is not one. */
export function cameIn(
  market: string,
  result: Pick<KnowledgeResult, "outcome" | "total" | "btts">,
  line: number | null,
): { selection: string | null; pushed: boolean } {
  if (market === "1X2") return { selection: result.outcome, pushed: false };
  if (market === "BTTS") return { selection: result.btts ? "Yes" : "No", pushed: false };
  if (market === "OU" && line !== null && Number.isInteger(line * 2)) {
    if (result.total > line) return { selection: "Over", pushed: false };
    if (result.total < line) return { selection: "Under", pushed: false };
    return { selection: null, pushed: true };
  }
  return { selection: null, pushed: false };
}

function selectionRank(market: string, selection: string): number {
  const at = (SELECTION_ORDER[market] ?? []).indexOf(selection);
  return at === -1 ? 99 : at;
}

/** What the market said of the three core lines, from its first reading to its last, and which selection came in. */
export function marketReads(after: AfterMatch): MarketRead[] {
  const markets = after.market.data?.markets;
  if (!markets) return [];
  const result = after.result.data;
  const reads: MarketRead[] = [];
  for (const market of MARKET_KEYS) {
    const block = markets[market];
    if (!block) continue;
    const line = block.line ?? null;
    const came = result ? cameIn(market, result, line) : { selection: null, pushed: false };
    const rows: MarketRow[] = [];
    for (const [selection, pair] of Object.entries(block.probabilities)) {
      const close = toNumber(pair[1]);
      if (close === null) continue;
      rows.push({
        selection,
        open: toNumber(pair[0]),
        close,
        happened: came.selection === selection,
      });
    }
    if (rows.length === 0) continue;
    rows.sort(
      (a, b) =>
        selectionRank(market, a.selection) - selectionRank(market, b.selection) ||
        a.selection.localeCompare(b.selection),
    );
    reads.push({
      market,
      line,
      rows,
      happened: came.selection,
      pushed: came.pushed,
      books: block.books,
      minutesToKickoff: block.minutes_to_kickoff,
    });
  }
  return reads;
}

function lineText(line: number | null): string {
  return line === null ? "0" : String(line);
}

export function marketHeading(read: Pick<MarketRead, "market" | "line">): string {
  return marketTitle(read.market, read.line === null ? null : lineText(read.line));
}

/** "Gana Nashville SC", "Empate", "Más de 2,5", "Sí". */
export function marketSelectionText(
  read: Pick<MarketRead, "market" | "line">,
  selection: string,
  sides: Sides,
): string {
  return selectionPhrase({ market: read.market, selection, line: lineText(read.line) }, sides);
}

/** "2 h 55 min", "45 min": how long before kick-off a reading was. */
export function beforeKickoff(minutes: number): string {
  const n = Math.max(0, Math.round(minutes));
  if (n < 60) return t("match.knowledge.minutes.short", { n });
  const h = Math.floor(n / 60);
  const m = n % 60;
  return m === 0
    ? t("match.knowledge.minutes.hours", { h })
    : t("match.knowledge.minutes.hoursMinutes", { h, m });
}

/** What the market gave to what happened, at the close, and where it had opened. Null when the result says no one selection. */
export function happenedNote(read: MarketRead): string | null {
  if (read.pushed) return t("match.knowledge.market.pushed");
  const came = read.rows.find((r) => r.happened);
  if (!came) return null;
  const close = fmtPct(came.close, 0);
  return came.open === null
    ? t("match.knowledge.market.happenedNow", { close })
    : t("match.knowledge.market.happenedFrom", { close, open: fmtPct(came.open, 0) });
}

/** When the closing reading was taken, and by how many bookmakers: the close is not the last minute before kick-off. */
export function closingNote(read: Pick<MarketRead, "books" | "minutesToKickoff">): string | null {
  if (read.minutesToKickoff === null) return null;
  const when = beforeKickoff(read.minutesToKickoff);
  return read.books === null
    ? t("match.knowledge.market.closingBare", { when })
    : t("match.knowledge.market.closing", { when, count: read.books });
}

// ── the players ─────────────────────────────────────────────────────────────

export interface PlayerLine {
  id: number;
  name: string | null;
  rating: number | null;
  minutes: number | null;
  goals: number;
  assists: number;
  /** Nobody in the match was rated higher. */
  best: boolean;
}

export interface BestPlayers {
  home: PlayerLine[];
  away: PlayerLine[];
}

/** The best rated of each side (at most three, as the API gives them), the best of the whole match marked. */
export function bestPlayers(after: AfterMatch): BestPlayers | null {
  const data = after.players.data;
  if (!data) return null;
  const read = (side: KnowledgeSide) =>
    (data[side]?.top ?? []).map((p) => ({
      id: p.player_id,
      name: p.name,
      rating: toNumber(p.rating),
      minutes: p.minutes,
      goals: p.goals,
      assists: p.assists,
    }));
  const home = read("home");
  const away = read("away");
  if (home.length === 0 && away.length === 0) return null;
  const ratings = [...home, ...away].flatMap((p) => (p.rating === null ? [] : [p.rating]));
  const top = ratings.length ? Math.max(...ratings) : null;
  const mark = (p: (typeof home)[number]): PlayerLine => ({
    ...p,
    best: top !== null && p.rating === top,
  });
  return { home: home.map(mark), away: away.map(mark) };
}

/** "90 min · 1 gol · 1 asistencia": only what the provider gave and what is not zero. */
export function playerFigures(p: Pick<PlayerLine, "minutes" | "goals" | "assists">): string[] {
  const out: string[] = [];
  if (p.minutes !== null && p.minutes > 0)
    out.push(t("match.players.minutes", { count: p.minutes }));
  if (p.goals > 0) out.push(t("match.players.goals", { count: p.goals }));
  if (p.assists > 0) out.push(t("match.players.assists", { count: p.assists }));
  return out;
}

// ── the formations and the changes ──────────────────────────────────────────

export interface SideLineup {
  formation: string | null;
  /** Each change: the minute, and the lead of the side at that moment in words (null when the events do not say). */
  subs: { minute: string; lead: string | null }[];
}

export interface Lineups {
  home: SideLineup | null;
  away: SideLineup | null;
}

/** The formation of each side and when it made its changes. Null when neither side has either. */
export function lineups(after: AfterMatch): Lineups | null {
  const data = after.tactics.data;
  if (!data) return null;
  const side = (s: typeof data.home): SideLineup | null => {
    if (!s) return null;
    const formation = s.formation?.trim() || null;
    const subs = s.substitutions.map((x) => ({
      minute: minuteText(x.minute, null),
      lead: leadText(x.lead),
    }));
    return formation === null && subs.length === 0 ? null : { formation, subs };
  };
  const home = side(data.home);
  const away = side(data.away);
  return home === null && away === null ? null : { home, away };
}

/** "58' (empatando)", or just "58'" when the events do not give the score. */
export function substitutionText(sub: { minute: string; lead: string | null }): string {
  return sub.lead
    ? t("match.knowledge.tactics.subLead", { minute: sub.minute, lead: sub.lead })
    : sub.minute;
}

// ── how far it can be trusted ───────────────────────────────────────────────

export function completenessLabel(c: KnowledgeCompleteness): string {
  return translateOr(`match.knowledge.quality.${c}`, c);
}

export function completenessNote(c: KnowledgeCompleteness): string {
  return translateOr(`match.knowledge.quality.${c}Note`, "");
}

/** What could not be said or may not be right, in the reader's language; a code this page does not know says so once. */
export function doubtTexts(after: Pick<AfterMatch, "quality">): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const code of after.quality.doubts) {
    const text = translateOr(`match.knowledge.doubt.${code}`, t("match.knowledge.doubt.other"));
    if (!seen.has(text)) {
      seen.add(text);
      out.push(text);
    }
  }
  return out;
}

// ── the row as stored (the Admin Console's preview) ─────────────────────────

export interface StoredLayer {
  name: string;
  status: string;
  knownAt: string | null;
  notes: string[];
  /** The decisions, the post-mortems and the external context as stored: for the preview alone, never a user's. */
  json: string | null;
}

/** Layers 7 to 9: the external context, the picks and the post-mortems. */
const OWN_LAYERS = /^c[789]_/;

export function storedLayers(stored: Pick<KnowledgeStoredBuild, "layers">): StoredLayer[] {
  return Object.entries(stored.layers)
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, layer]) => {
      const status = layer["status"];
      const knownAt = layer["known_at"];
      const notes = layer["notes"];
      return {
        name,
        status: typeof status === "string" ? status : "—",
        knownAt: typeof knownAt === "string" ? knownAt : null,
        notes: Array.isArray(notes) ? notes.filter((n): n is string => typeof n === "string") : [],
        json:
          OWN_LAYERS.test(name) && layer["data"] !== undefined
            ? JSON.stringify(layer["data"], null, 1)
            : null,
      };
    });
}

/** A hash as the preview shows it: enough to tell two builds apart. */
export function shortHash(hash: string): string {
  return hash.slice(0, 12);
}

export interface FinalRead {
  market: string;
  line: number | null;
  /** "Home 1,85 · Draw 3,60 · Away 4,20". */
  odds: string;
  books: number;
  /** How long before kick-off the provider last moved them. */
  before: string;
  at: string;
}

/**
 * The provider's last pre-match prices of every market the row has (handicaps too), the middle of the bookmakers' own prices and
 * not de-vigged. A price, so the preview's alone: a user is shown the probabilities of the market, never these.
 */
export function finalReads(after: AfterMatch): FinalRead[] {
  const markets = after.market.data?.markets;
  if (!markets) return [];
  return Object.entries(markets).flatMap(([market, block]) =>
    block.final
      ? [
          {
            market,
            line: block.line ?? null,
            odds: Object.entries(block.final.odds)
              .map(([selection, odds]) => `${selection} ${fmtOdds(odds)}`)
              .join(" · "),
            books: block.final.books,
            before: beforeKickoff(block.final.minutes_to_kickoff),
            at: block.final.at,
          },
        ]
      : [],
  );
}
