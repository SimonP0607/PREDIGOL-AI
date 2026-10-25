/**
 * The words of the families in shadow (plan F10.17 and F11.11): the pure part of the "Familias" tab of Aprendizaje. The families bet on markets
 * the rest of the console has no names for - the corners of the match, the cards, the yellows, the goals of one half - and the server sends
 * their keys as the catalogue makes them (`CORNERS_OU_HOME`, `OU_2H`, `HTFT`), so this file reads a key by its parts, names each part in the
 * reader's language and puts them together; a key it cannot read is shown as it came, never guessed. It knows nothing of React.
 *
 * `measureOf` is the web's copy of `fbi.api.services.families.measure_of` (itself held equal to `fbi.families.score.measure_of`): which measure
 * of the finished match grades a bet. Its test lists every key the families state.
 */
import { hasKey, t, translateOr } from "@/lib/i18n";
import { fmtLine, localFixed, localInt, toNumber } from "@/lib/i18n/format";
import type { FamiliesRule } from "@/lib/api/v1/types_families";
import type { BadgeTone } from "@/components/primitives/StatusBadge";

/** The families that decide, in the order the tab shows them (the server's own order). */
export const FAMILY_CODES = ["GOALS_HALF", "CORNERS", "CARDS", "YELLOW"] as const;

/** The steps of the cycle, in the order the worker runs them. */
export const STEPS = [
  "families",
  "family_outcomes",
  "family_postmortems",
  "family_memory",
] as const;

/** What the console says of a step: the figures its report carries that are worth a line (the rest stays in the run's record). */
const STEP_FACTS: Record<string, readonly string[]> = {
  families: ["forecasts", "candidates", "written", "failed"],
  family_outcomes: ["open", "settled", "no_close", "failed"],
  family_postmortems: ["open", "written", "unreadable", "failed"],
  family_memory: ["postmortems", "entities", "written", "unchanged"],
};

export const WINDOWS = [7, 14, 30, 60, 120] as const;

// ── what a market key is made of ─────────────────────────────────────────────────────────────────────────────────────────

type Count = "goals" | "corners" | "cards" | "yellow";
type Subject = "" | "home" | "away";
type Half = "" | "1H" | "2H";

export interface MarketShape {
  /** What is counted: the goals (no prefix), the corners, the cards or the yellow cards. */
  count: Count;
  /** The kind of bet: OU, 1X2, DC, DNB, BTTS, AH or OE. */
  kind: string;
  subject: Subject;
  half: Half;
}

const PREFIXES: ReadonlyArray<readonly [string, Count]> = [
  ["CORNERS_", "corners"],
  ["CARDS_", "cards"],
  ["YELLOW_", "yellow"],
];
const KINDS = ["OU", "1X2", "DC", "DNB", "BTTS", "AH", "OE"] as const;
/** The keys that read both halves of the goals, which have a name of their own. */
const SPECIALS = ["HTFT", "HSH", "HSH_HOME", "HSH_AWAY"] as const;

/** The measure of the settlement rules that grades a bet on this market key, or null for a key no family bets on. */
export function measureOf(key: string): string | null {
  if (key.startsWith("CORNERS_")) return "corners_ft";
  if (key.startsWith("CARDS_")) return "cards_lines_ft";
  if (key.startsWith("YELLOW_")) return "yellow_ft";
  if ((SPECIALS as readonly string[]).includes(key)) return "goals_halves";
  if (key.endsWith("_1H")) return "goals_1h";
  if (key.endsWith("_2H")) return "goals_2h";
  return null;
}

/** True when the key is one a family bets on. */
export function isFamilyMarket(key: string): boolean {
  return measureOf(key) !== null;
}

/** A key read by its parts - `CORNERS_OU_HOME` is the over/under of the home corners, `OU_2H` that of the goals of the 2nd half - or null. */
export function shapeOf(key: string): MarketShape | null {
  let rest = key;
  let count: Count = "goals";
  for (const [prefix, found] of PREFIXES) {
    if (rest.startsWith(prefix)) {
      count = found;
      rest = rest.slice(prefix.length);
      break;
    }
  }
  let half: Half = "";
  if (rest.endsWith("_1H")) {
    half = "1H";
    rest = rest.slice(0, -3);
  } else if (rest.endsWith("_2H")) {
    half = "2H";
    rest = rest.slice(0, -3);
  }
  let subject: Subject = "";
  if (rest.endsWith("_HOME")) {
    subject = "home";
    rest = rest.slice(0, -5);
  } else if (rest.endsWith("_AWAY")) {
    subject = "away";
    rest = rest.slice(0, -5);
  }
  return (KINDS as readonly string[]).includes(rest) ? { count, kind: rest, subject, half } : null;
}

function upperFirst(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** "Córners del local · más/menos", "Goles · más/menos · 1.ª parte", "Descanso/final": the market in words. A key it cannot read comes back as it is. */
export function marketText(key: string): string {
  if ((SPECIALS as readonly string[]).includes(key))
    return translateOr(`families.special.${key}`, key);
  const shape = shapeOf(key);
  if (shape === null) return key;
  const subject = shape.subject === "" ? "" : `_${shape.subject}`;
  // The 1X2, the double chance, both-teams-to-score... of the goals need no "Goles" in front of them: the half says what they are about.
  const what =
    shape.count === "goals" && shape.subject === "" && shape.kind !== "OU"
      ? ""
      : t(`families.what.${shape.count}${subject}`);
  const kind = t(`families.kind.${shape.kind}`);
  const half = shape.half === "" ? "" : t(`families.half.${shape.half}`);
  return upperFirst([what, kind, half].filter((part) => part !== "").join(" · "));
}

/** The teams of the match, when the server named them: the selections then say "Barcelona" and not "Local". */
export interface Teams {
  home?: string | null | undefined;
  away?: string | null | undefined;
}

function side(which: "Home" | "Draw" | "Away", teams: Teams | undefined): string {
  if (which === "Home") return teams?.home || t("families.pick.home");
  if (which === "Away") return teams?.away || t("families.pick.away");
  return t("families.pick.draw");
}

function sideOf(word: string, teams: Teams | undefined): string | null {
  const w = word.trim().toLowerCase();
  if (w === "home") return side("Home", teams);
  if (w === "draw") return side("Draw", teams);
  if (w === "away") return side("Away", teams);
  return null;
}

/**
 * The selection in words: "Más de 9,5", "Barcelona o empate", "Sí", "Real Madrid / Empate" (half-time/full-time), "2.ª parte". `line` is the
 * line of the bet where it has one. A selection this does not know comes back as it is (with the line, if there is one).
 */
export function pickText(
  key: string,
  selection: string,
  line: number | string | null | undefined,
  teams?: Teams,
): string {
  const word = selection.trim().toLowerCase();
  const n = toNumber(line);
  if ((SPECIALS as readonly string[]).includes(key)) {
    if (key === "HTFT") {
      const parts = selection.split("/").map((part) => sideOf(part, teams));
      if (parts.length === 2 && parts.every((part) => part !== null)) return parts.join(" / ");
    } else if (word === "1st half") {
      return t("families.pick.half1");
    } else if (word === "2nd half") {
      return t("families.pick.half2");
    } else if (word === "draw") {
      return t("families.pick.halfDraw");
    }
    return selection;
  }
  const shape = shapeOf(key);
  const home = side("Home", teams);
  const away = side("Away", teams);
  const fallback = n === null ? selection : `${selection} ${fmtLine(n)}`;
  if (shape === null) return fallback;
  switch (shape.kind) {
    case "OU":
      if (word === "over") {
        return n === null
          ? t("families.pick.overNoLine")
          : t("families.pick.over", { line: fmtLine(n) });
      }
      if (word === "under") {
        return n === null
          ? t("families.pick.underNoLine")
          : t("families.pick.under", { line: fmtLine(n) });
      }
      return fallback;
    case "1X2":
    case "DNB":
      return sideOf(word, teams) ?? fallback;
    case "DC":
      if (word === "1x") return t("families.pick.dc1X", { home });
      if (word === "12") return t("families.pick.dc12", { home, away });
      if (word === "x2") return t("families.pick.dcX2", { away });
      return fallback;
    case "BTTS":
      if (word === "yes") return t("families.pick.yes");
      if (word === "no") return t("families.pick.no");
      return fallback;
    case "OE":
      if (word === "odd") return t("families.pick.odd");
      if (word === "even") return t("families.pick.even");
      return fallback;
    case "AH":
      if (word === "home" || word === "away") {
        return t("families.pick.handicap", {
          team: word === "home" ? home : away,
          line: n === null ? "" : fmtLine(n, true),
        }).trim();
      }
      return fallback;
    default:
      return fallback;
  }
}

// ── the cycle ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export function familyName(code: string): string {
  return translateOr(`families.family.${code}`, code);
}

export function stepName(step: string): string {
  return translateOr(`families.step.${step}`, step);
}

export function statusName(status: string): string {
  return translateOr(`families.status.${status}`, status);
}

export interface StepFact {
  key: string;
  label: string;
  value: string;
}

/** The figures of a step's report that the tab shows: only those the run carried, as whole numbers. */
export function stepFacts(step: string, result: Record<string, unknown>): StepFact[] {
  return (STEP_FACTS[step] ?? []).flatMap((key) => {
    const value = result[key];
    return typeof value === "number" && Number.isFinite(value)
      ? [{ key, label: translateOr(`families.fact.${key}`, key), value: localInt(value) }]
      : [];
  });
}

/** How long a step took: "850 ms", "2,4 s". */
export function msText(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  return ms < 1000 ? `${localInt(ms)} ms` : `${localFixed(ms / 1000, 1)} s`;
}

// ── what became of a decision ────────────────────────────────────────────────────────────────────────────────────────────

export function resultName(result: string): string {
  return translateOr(`families.result.${result}`, result);
}

export function verdictName(verdict: string): string {
  return translateOr(`intel.codes.verdict.${verdict}`, verdict);
}

export function verdictHint(verdict: string): string {
  return translateOr(`families.verdictHint.${verdict}`, "");
}

export function qualityName(quality: string): string {
  return translateOr(`families.quality.${quality}`, quality);
}

export function stateName(state: string): string {
  return translateOr(`intel.state.${state}`, state);
}

export function reasonName(reason: string): string {
  return translateOr(`families.reason.${reason}`, reason);
}

// ── how a bet is graded ──────────────────────────────────────────────────────────────────────────────────────────────────

/** What a rule measures, in the reader's language; a rule the catalog has no words for says what the registry says (in English). */
export function ruleText(rule: FamiliesRule): string {
  return translateOr(`families.rule.${rule.measure}`, rule.convention);
}

/** What the registry warns about a rule, or an empty text. */
export function ruleNote(rule: FamiliesRule): string {
  if (hasKey(`families.rule.${rule.measure}`))
    return translateOr(`families.ruleNote.${rule.measure}`, "");
  return rule.note;
}

// ── the tone of each word (green when it is good news for the family, red when it is not) ────────────────────────────────

const VERDICT_TONE: Record<string, BadgeTone> = {
  MERECIDO: "positive",
  VARIANZA: "info",
  SUERTE: "warning",
  ERROR: "negative",
  NULO: "neutral",
  SIN_DATOS: "neutral",
};
const RESULT_TONE: Record<string, BadgeTone> = {
  win: "positive",
  half_win: "positive",
  loss: "negative",
  half_loss: "negative",
  push: "neutral",
  void: "neutral",
};
const STEP_TONE: Record<string, BadgeTone> = {
  ok: "positive",
  partial: "warning",
  failed: "negative",
  interrupted: "warning",
  running: "info",
  skipped: "neutral",
};
/** The same tones the rest of the console gives the two states a family can reach. */
const STATE_TONE: Record<string, BadgeTone> = { INVESTIGACION: "info", RECHAZADO: "negative" };

export function verdictTone(verdict: string): BadgeTone {
  return VERDICT_TONE[verdict] ?? "neutral";
}
export function resultTone(result: string): BadgeTone {
  return RESULT_TONE[result] ?? "neutral";
}
export function stepTone(status: string): BadgeTone {
  return STEP_TONE[status] ?? "neutral";
}
export function stateTone(state: string): BadgeTone {
  return STATE_TONE[state] ?? "neutral";
}

// ── the mode of the cycle ────────────────────────────────────────────────────────────────────────────────────────────────

/** What the worker did in its latest run of a step: `shadow`, `off`, or nothing when it has not run one in the lookback. */
export function modeName(mode: string | null): string {
  if (mode === null) return t("families.mode.none");
  return translateOr(`families.mode.${mode}`, mode);
}

export function modeTone(mode: string | null): BadgeTone {
  return mode === "shadow" ? "info" : "neutral";
}

/** Why the cycle is not running, when it is not: the switch is off, or no pass was seen in the lookback. */
export function modeHelp(mode: string | null): string | null {
  if (mode === "shadow") return null;
  return mode === null ? t("families.mode.noneHelp") : t("families.mode.offHelp");
}

/** The reasons of a decision that say something: every family decision carries `family_research`, which the state already says. */
export function reasonsShown(reasons: readonly string[]): string[] {
  return reasons.filter((reason) => reason !== "family_research").map(reasonName);
}
