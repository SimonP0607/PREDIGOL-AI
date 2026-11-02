/**
 * PLAN F6 in the Admin Console, as plain data: the dossier's picker (a day, or a text) and the blocks of the AI's
 * packet and brief that the owner reads - the weighted head-to-head, what the match does to its table and its tie,
 * the observable tactics, the status of each context factor, what the AI asked the server to look into, what the
 * server did about it and every claim it refused. Everything here is a function of the API's rows, so the panels
 * (IntelMatchPanels.tsx, IntelAiPanels.tsx) only lay them out and the rules are tested without a browser.
 *
 * Nothing here moves a number: the weights, the statuses and the counts are shown as the server states them.
 */
import { t, translateOr } from "@/lib/i18n";
import { fmtPct, localFixed, localInt } from "@/lib/i18n/format";
import type {
  IntelBrief,
  IntelFactorEntry,
  IntelFactorRow,
  IntelFactorsBlock,
  IntelFactorStatus,
  IntelH2hBlock,
  IntelH2hMeeting,
  IntelH2hRecord,
  IntelPass,
  IntelPickerRow,
  IntelRefusedClaim,
  IntelResearchAsk,
  IntelScenarioResult,
  IntelScenarioSide,
  IntelScenarioTable,
  IntelScenariosBlock,
  IntelScenarioTie,
  IntelTacticsProfile,
  IntelTally,
  IntelTieSide,
} from "@/lib/api/v1/types_intel";

export const DASH = "—";

// ── the picker ───────────────────────────────────────────────────────────────

/** The text of a search as the server will read it: spaces collapsed, at most the 60 characters it accepts. */
export function searchText(raw: string): string {
  return raw.replace(/\s+/g, " ").trim().slice(0, 60);
}

/**
 * A text is worth sending once it can name something: two characters of a team or competition, or a match id (digits).
 * One letter would list every match with a name that holds it.
 */
export function canSearch(raw: string): boolean {
  const text = searchText(raw);
  return text.length >= 2 || /^\d+$/.test(text);
}

/** The parameters of the picker's query: the day (the server's today when none) and the text only when it can search. */
export function pickerParams(
  raw: string,
  day: string | undefined,
): { day?: string | undefined; q?: string | undefined } {
  return { day, q: canSearch(raw) ? searchText(raw) : undefined };
}

export interface PickerBadge {
  key: "studied" | "unstudied" | "research" | "escalated";
  /** The words, ready to show. */
  text: string;
  tone: "positive" | "neutral" | "info" | "warning";
}

/** What the picker says about a match besides its name: did the AI study it, did its brief ask for research, did it escalate. */
export function pickerBadges(row: IntelPickerRow): PickerBadge[] {
  const out: PickerBadge[] = [
    row.packet_as_of
      ? { key: "studied", text: t("intel.match.picker.studied"), tone: "positive" }
      : { key: "unstudied", text: t("intel.match.picker.unstudied"), tone: "neutral" },
  ];
  if (row.research_asked > 0)
    out.push({
      key: "research",
      text: t("intel.match.picker.research", { count: row.research_asked }),
      tone: "info",
    });
  if (row.brief_escalate)
    out.push({ key: "escalated", text: t("intel.match.picker.escalated"), tone: "warning" });
  return out;
}

// ── time ─────────────────────────────────────────────────────────────────────

/** An age in days in the largest unit that keeps it exact enough to read: "12 días", "7 meses", "2,5 años". */
export function ageText(days: number | null | undefined): string {
  if (days === null || days === undefined || !Number.isFinite(days)) return DASH;
  const d = Math.max(0, Math.round(days));
  if (d < 60) return t("intel.match.age.days", { count: d });
  if (d < 730) return t("intel.match.age.months", { count: Math.round(d / 30.44) });
  return t("intel.match.age.years", { years: localFixed(d / 365.25, 1) });
}

// ── the weighted head-to-head ────────────────────────────────────────────────

export interface MeetingRow {
  id: number;
  age: string;
  competition: string;
  /** The words for the kind of meeting ("misma competición") and the ground the match's home side played on. */
  scope: string;
  ground: string;
  /** "2–1" in 90 minutes, from the point of view of the match's home side. */
  score: string;
  afterExtraTime: boolean;
  /** "0,63". */
  weight: string;
  /** The share of all the weights this meeting carries, as a percentage: "31 %". */
  share: string;
  coaches: string;
}

export interface H2hView {
  n: number;
  nEffective: string;
  relevance: string;
  lastAgo: string;
  oldestAgo: string;
  /** "3 G · 2 E · 1 P" - the raw count in 90 minutes seen from the match's home side - or null with no meetings. */
  record: string | null;
  sameVenue: string | null;
  /** "46 % · 28 % · 26 %". */
  weighted: string | null;
  goalsPerMeeting: string | null;
  coaches: string | null;
  meetings: MeetingRow[];
  note: string;
  weightsNote: string | null;
}

function recordText(r: IntelH2hRecord | null | undefined): string | null {
  if (!r || r.n === 0) return null;
  return t("intel.match.h2hw.recordText", {
    w: r.home_side_wins,
    d: r.draws,
    l: r.away_side_wins,
  });
}

function coachesOf(m: IntelH2hMeeting): string {
  const { home, away } = m.coach_changed;
  if (home === true && away === true) return t("intel.match.h2hw.coach.both");
  if (home === true) return t("intel.match.h2hw.coach.home");
  if (away === true) return t("intel.match.h2hw.coach.away");
  if (home === false && away === false) return t("intel.match.h2hw.coach.none");
  return t("intel.match.h2hw.coach.unknown");
}

/** The weighted head-to-head of the packet as the owner reads it. */
export function h2hView(block: IntelH2hBlock): H2hView {
  const meetings = block.meetings ?? [];
  const total = meetings.reduce((sum, m) => sum + m.weight, 0);
  const w = block.weighted ?? null;
  const c = block.coaches;
  return {
    n: block.n,
    nEffective: localFixed(block.n_effective, 1),
    relevance: block.relevance,
    lastAgo: ageText(block.last_days_ago),
    oldestAgo: ageText(block.oldest_days_ago),
    record: recordText(block.record),
    sameVenue: recordText(block.same_venue),
    weighted: w
      ? [w.home_side_win, w.draw, w.away_side_win].map((x) => fmtPct(x, 0)).join(" · ")
      : null,
    goalsPerMeeting: w
      ? `${localFixed(w.goals_home_side_pg, 2)} – ${localFixed(w.goals_away_side_pg, 2)}`
      : null,
    coaches: c
      ? t("intel.match.h2hw.coachesText", {
          same: c.both_same,
          changed: c.some_changed,
          unknown: c.unknown,
        })
      : null,
    meetings: meetings.map((m) => ({
      id: m.fixture_id,
      age: ageText(m.days_ago),
      competition: m.competition,
      scope: translateOr(`center.context.h2h.scope.${m.scope}`, m.scope),
      ground: translateOr(`center.context.h2h.ground.${m.home_side_was}`, m.home_side_was),
      score: `${m.goals_home_side}–${m.goals_away_side}`,
      afterExtraTime: m.after_extra_time,
      weight: localFixed(m.weight, 2),
      share: total > 0 ? fmtPct(m.weight / total, 0) : DASH,
      coaches: coachesOf(m),
    })),
    note: block.note,
    weightsNote: block.weights_note ?? null,
  };
}

// ── what the match does to its table and its tie ────────────────────────────

/** "puesto 3" or "puestos 3–5": the interval of places a result leaves a side in. */
export function placesText(best: number, worst: number): string {
  return best === worst
    ? t("intel.match.scen.place", { n: best })
    : t("intel.match.scen.places", { best, worst });
}

function sideAfter(s: IntelScenarioSide): string {
  const zones = s.zones
    .map((z) => z.description)
    .filter((d): d is string => typeof d === "string" && d !== "");
  const head = `${t("intel.match.scen.points", { points: s.points })} · ${placesText(s.rank_best, s.rank_worst)}`;
  return zones.length ? `${head} · ${zones.join(" / ")}` : head;
}

export const SCENARIO_RESULTS: readonly IntelScenarioResult[] = ["home_win", "draw", "away_win"];

export interface TableView {
  group: string | null;
  snapshotAt: string | null;
  /** Set when the table is not ordered by its points: nothing is read from it. */
  unavailable: boolean;
  home: string | null;
  away: string | null;
  rows: Array<{ result: IntelScenarioResult; home: string; away: string }>;
}

function nowText(side: NonNullable<IntelScenarioTable["home"]>): string {
  const head = t("intel.match.scen.now", {
    rank: side.rank_now,
    points: side.points_now,
    played: side.played,
  });
  return side.zone_now ? `${head} · ${side.zone_now}` : head;
}

export function tableView(table: IntelScenarioTable): TableView {
  const after = table.after;
  return {
    group: table.group,
    snapshotAt: table.snapshot_at,
    unavailable: table.unavailable !== undefined,
    home: table.home ? nowText(table.home) : null,
    away: table.away ? nowText(table.away) : null,
    rows: after
      ? SCENARIO_RESULTS.filter((r) => after[r] !== undefined).map((r) => ({
          result: r,
          home: sideAfter(after[r].home),
          away: sideAfter(after[r].away),
        }))
      : [],
  };
}

/** "+1", "0", "−2": a goal margin with its sign. */
export function marginText(n: number): string {
  if (n === 0) return "0";
  return n > 0 ? `+${n}` : `−${Math.abs(n)}`;
}

export interface TieView {
  kind: string;
  /** The tie's kind in the owner's words ("partido de vuelta"). */
  kindLabel: string;
  /** The text the server wrote when it cannot read the tie ("falta el resultado de la ida"). */
  note: string | null;
  /** "1–0": the aggregate before the match, the match's home side first. */
  before: string | null;
  /** A series: "juego 3 · 1–1, 1 empate". */
  series: string | null;
  margin: string | null;
  sides: Array<{
    side: "home" | "away";
    ahead: string;
    level: string;
    behind: string;
    limit: string;
  }>;
}

function tieSide(s: IntelTieSide): { ahead: string; level: string; behind: string; limit: string } {
  return {
    ahead: `≥ ${marginText(s.ahead_if_margin_at_least)}`,
    level: marginText(s.level_if_margin),
    behind: `≤ ${marginText(s.behind_if_margin_at_most)}`,
    limit:
      s.can_lose_by_up_to === 0
        ? t("intel.match.scen.cannotLose")
        : s.can_lose_by_up_to !== null
          ? t("intel.match.scen.canLose", { n: s.can_lose_by_up_to })
          : s.needs_to_win_by_at_least !== null
            ? t("intel.match.scen.needsWin", { n: s.needs_to_win_by_at_least })
            : DASH,
  };
}

export function tieView(tie: IntelScenarioTie): TieView {
  const sides: TieView["sides"] = [];
  if (tie.home_side) sides.push({ side: "home", ...tieSide(tie.home_side) });
  if (tie.away_side) sides.push({ side: "away", ...tieSide(tie.away_side) });
  return {
    kind: tie.kind,
    kindLabel: translateOr(`intel.match.scen.kind.${tie.kind}`, tie.kind.replace(/_/g, " ")),
    note: tie.note ?? null,
    before: tie.aggregate_before
      ? `${tie.aggregate_before.home_side}–${tie.aggregate_before.away_side}`
      : null,
    series:
      tie.kind === "series" && tie.game !== undefined
        ? t("intel.match.scen.seriesText", {
            game: tie.game,
            home: tie.wins_home_side ?? 0,
            away: tie.wins_away_side ?? 0,
            draws: tie.draws ?? 0,
          })
        : null,
    margin: tie.margin ?? null,
    sides,
  };
}

/** Is there anything to show in the scenarios block? */
export function hasScenarios(block: IntelScenariosBlock | null | undefined): boolean {
  return !!block && (block.table !== null || block.tie !== null);
}

// ── the observable tactics ───────────────────────────────────────────────────

export interface TacticsRow {
  key: string;
  home: string;
  away: string;
}

/** "4G 3E 3P" with the size of the sample it comes from. */
function tallyText(x: IntelTally | undefined): string {
  if (!x || x.n === 0) return DASH;
  return `${t("intel.match.tactics.tally", { w: x.wins, d: x.draws, l: x.losses })} (${x.n})`;
}

function sampleText(n: number, of: number): string {
  return t("intel.match.tactics.sample", { n, of });
}

function formationText(p: IntelTacticsProfile): string {
  const f = p.formations;
  if (!f || f.n === 0 || !f.main) return DASH;
  return t("intel.match.tactics.formationText", {
    main: f.main,
    count: f.main_count ?? 0,
    n: f.n,
    last: f.last ?? DASH,
    changes: f.changes ?? 0,
  });
}

function rotationText(p: IntelTacticsProfile): string {
  const s = p.starters;
  if (!s || s.n === 0 || s.avg_changes === null || s.avg_changes === undefined) return DASH;
  return t("intel.match.tactics.rotationText", {
    avg: localFixed(s.avg_changes, 1),
    pairs: s.pairs ?? 0,
  });
}

function coachText(p: IntelTacticsProfile): string {
  const c = p.coach;
  if (!c || c.n === 0) return DASH;
  return t("intel.match.tactics.coachText", {
    newest: c.newest_matches ?? 0,
    n: c.n,
    distinct: c.distinct ?? 0,
  });
}

function goalsText(p: IntelTacticsProfile): string {
  const g = p.goals;
  if (!g || g.n === 0) return DASH;
  return t("intel.match.tactics.goalsText", {
    for: g.total_for ?? 0,
    against: g.total_against ?? 0,
    n: g.n,
  });
}

function lateText(p: IntelTacticsProfile): string {
  const g = p.goals;
  if (!g || g.n === 0 || !g.late) return DASH;
  return t("intel.match.tactics.lateText", {
    for: g.late.for,
    against: g.late.against,
    n: g.n,
  });
}

function firstSubText(p: IntelTacticsProfile): string {
  const s = p.substitutions;
  const mean = s?.first_minute?.mean;
  if (!s || s.n === 0 || mean === null || mean === undefined) return DASH;
  return t("intel.match.tactics.firstSubText", {
    mean: localFixed(mean, 1),
    n: s.with_substitutions ?? 0,
    of: s.n,
  });
}

function dataText(p: IntelTacticsProfile): string {
  const d = p.data;
  if (!d) return DASH;
  const parts: string[] = [];
  if (d.sheets.none) parts.push(t("intel.match.tactics.noSheet", { count: d.sheets.none }));
  if (d.sheets.crossed) parts.push(t("intel.match.tactics.crossed", { count: d.sheets.crossed }));
  if (d.events.none) parts.push(t("intel.match.tactics.noEvents", { count: d.events.none }));
  if (d.events.inconsistent)
    parts.push(t("intel.match.tactics.inconsistent", { count: d.events.inconsistent }));
  return parts.length ? parts.join(" · ") : t("intel.match.tactics.complete");
}

/** The rows of the tactics table, home beside away; every figure carries the size of its sample. */
export function tacticsRows(home: IntelTacticsProfile, away: IntelTacticsProfile): TacticsRow[] {
  const both = (f: (p: IntelTacticsProfile) => string): { home: string; away: string } => ({
    home: f(home),
    away: f(away),
  });
  return [
    { key: "read", ...both((p) => sampleText(p.goals?.n ?? 0, p.n)) },
    { key: "data", ...both(dataText) },
    { key: "formation", ...both(formationText) },
    { key: "rotation", ...both(rotationText) },
    { key: "coach", ...both(coachText) },
    { key: "goals", ...both(goalsText) },
    { key: "late", ...both(lateText) },
    { key: "scoredFirst", ...both((p) => tallyText(p.with_the_score?.scored_first)) },
    { key: "concededFirst", ...both((p) => tallyText(p.with_the_score?.conceded_first)) },
    { key: "htLeading", ...both((p) => tallyText(p.with_the_score?.half_time.leading)) },
    { key: "htTrailing", ...both((p) => tallyText(p.with_the_score?.half_time.trailing)) },
    { key: "firstSub", ...both(firstSubText) },
  ];
}

// ── the context factors ──────────────────────────────────────────────────────

const FACTOR_META = new Set(["version", "note", "error"]);

/** The factors the packet states (every key of the block that is not its version, note or error). */
export function factorEntries(
  block: IntelFactorsBlock | null | undefined,
): Array<{ key: string; entry: IntelFactorEntry }> {
  if (!block) return [];
  return Object.keys(block)
    .filter((k) => !FACTOR_META.has(k))
    .flatMap((k) => {
      const v = block[k];
      return v !== undefined && typeof v === "object" ? [{ key: k, entry: v }] : [];
    });
}

export function factorStatus(status: string): IntelFactorStatus {
  return status === "VALIDATED" ? "VALIDATED" : "DESCRIPTIVE";
}

export function factorName(key: string, fallback?: string): string {
  return translateOr(`intel.match.factors.labels.${key}`, fallback ?? key.replace(/_/g, " "));
}

export interface FactorLine {
  key: string;
  name: string;
  /** What the packet said when the AI read it. */
  packet: IntelFactorStatus;
  experiment: string | null;
  /** The registry today (undefined while it is loading or unreadable). */
  today?: IntelFactorStatus | undefined;
  /** The registry says something else today than the packet did. */
  changed: boolean;
}

/** The packet's factors beside the registry as it stands, so a change after the packet shows. */
export function factorLines(
  block: IntelFactorsBlock | null | undefined,
  registry: readonly IntelFactorRow[] | undefined,
): FactorLine[] {
  const now = new Map((registry ?? []).map((f) => [f.key, f]));
  return factorEntries(block).map(({ key, entry }) => {
    const today = now.get(key);
    const packet = factorStatus(entry.status);
    return {
      key,
      name: factorName(key, today?.label),
      packet,
      experiment: entry.decision?.experiment ?? null,
      today: today?.status,
      changed: today !== undefined && today.status !== packet,
    };
  });
}

// ── what the AI asked, what the server did, what it refused ─────────────────

export interface AskLine {
  topic: string;
  side: string;
  reason: string;
  refs: string[];
}

export function askLines(asks: readonly IntelResearchAsk[] | undefined): AskLine[] {
  return (asks ?? []).map((a) => ({
    topic: translateOr(`intel.match.research.topic.${a.topic}`, a.topic),
    side: translateOr(`intel.match.research.side.${a.side}`, a.side),
    reason: a.why.text ?? DASH,
    refs: a.why.refs ?? [],
  }));
}

/** "sin cupo de búsquedas: 1 · cerca del presupuesto: 2": why requests were left unserved. */
export function unservedText(unserved: Record<string, number>): string {
  const parts = Object.keys(unserved)
    .sort()
    .filter((k) => (unserved[k] ?? 0) > 0)
    .map(
      (k) =>
        `${translateOr(`intel.match.research.unserved.${k}`, k.replace(/_/g, " "))}: ${unserved[k]}`,
    );
  return parts.length ? parts.join(" · ") : DASH;
}

export interface PassLine {
  pass: string;
  status: string;
  finishedAt: string;
  /** Requests the pass found in the previous brief / served / left unserved (with why). */
  asked: string;
  searched: string;
  unserved: string;
  /** The brief the pass wrote asked for research. */
  requested: string;
  webSearches: string;
  escalated: boolean;
  cost: number;
}

export function passLines(passes: readonly IntelPass[] | undefined): PassLine[] {
  return (passes ?? []).map((p) => ({
    pass: p.pass,
    status: p.status,
    finishedAt: p.finished_at,
    asked: localInt(p.research.asked),
    searched: localInt(p.research.searched),
    unserved: unservedText(p.research.unserved),
    requested: localInt(p.research.requested),
    webSearches: localInt(p.research.web_searches),
    escalated: p.escalated,
    cost: p.cost_usd,
  }));
}

const DESCRIPTIVE_REFUSAL = /^rests on (\w+), a DESCRIPTIVE factor/;

export interface RefusedLine {
  group: string;
  groupLabel: string;
  text: string;
  why: string;
  /** The factor the claim rested on when it was refused for resting on a DESCRIPTIVE one. */
  factor: string | null;
}

/** The group of a refused claim in the owner's words: "cards.why" -> "Por qué de las selecciones". */
export function refusedGroupLabel(group: string): string {
  if (group.startsWith("narrative.")) {
    return `${t("intel.match.refused.group.narrative")} · ${group.slice("narrative.".length)}`;
  }
  return translateOr(`intel.match.refused.group.${group.replace(/\./g, "_")}`, group);
}

export function refusedLines(refused: readonly IntelRefusedClaim[] | undefined): RefusedLine[] {
  return (refused ?? []).map((c) => ({
    group: c.group,
    groupLabel: refusedGroupLabel(c.group),
    text: c.text,
    why: c.why,
    factor: DESCRIPTIVE_REFUSAL.exec(c.why)?.[1] ?? null,
  }));
}

/** The brief's own flags, as short phrases: the engine, the uncertainty, the quality of the data. */
export function briefFlags(
  brief: Pick<IntelBrief, "engine" | "uncertainty" | "data_quality" | "escalate">,
): Array<{ key: string; label: string; value: string }> {
  const out = [
    {
      key: "engine",
      label: t("intel.match.brief.engine"),
      value: t(brief.engine === "llm" ? "intel.match.brief.byLlm" : "intel.match.brief.byRules"),
    },
  ];
  if (brief.uncertainty)
    out.push({
      key: "uncertainty",
      label: t("intel.match.brief.uncertainty"),
      value: translateOr(`intel.match.brief.level.${brief.uncertainty}`, brief.uncertainty),
    });
  if (brief.data_quality)
    out.push({
      key: "quality",
      label: t("intel.match.brief.quality"),
      value: translateOr(`intel.match.brief.dataQuality.${brief.data_quality}`, brief.data_quality),
    });
  out.push({
    key: "escalate",
    label: t("intel.match.brief.escalate"),
    value: brief.escalate ? t("intel.match.yes") : t("intel.match.no"),
  });
  return out;
}
