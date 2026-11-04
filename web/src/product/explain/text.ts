/**
 * «Explícame» in the reader's words (plan UX, B9; section 26's rules). Every line the API sends is a stable code with its
 * parameters (explain.say.<code>) or a fact of the match's structured reading, which the reading's own template writes
 * (src/product/reading/text.ts). A code this page does not know, or a line without a parameter it needs, is left out -
 * never shown raw, never with a gap. No template promises anything ("seguro", "fijo", "garantizado") or says how much to
 * stake; probabilities are always PrediGol's or the market's, labelled.
 */
import { hasKey, t, translateOr } from "@/lib/i18n";
import { DASH, fmtPct } from "@/lib/i18n/format";
import type {
  ExplainEntity,
  ExplainIntent,
  ExplainLine,
  ExplainParam,
  Explanation,
} from "@/lib/api/v1/types_explain";
import { factText } from "@/product/reading/text";
import { marketName, selectionLabel } from "@/product/shared/markets";

type P = Record<string, ExplainParam>;

/** The questions of each place, in the order the sheet lists them (fbi.api.services.explain.INTENTS). */
export const QUESTIONS: Readonly<Record<ExplainEntity, readonly ExplainIntent[]>> = {
  match: ["no_pick", "forecast", "risks"],
  pick: ["risks", "caution"],
  parlay: ["probability"],
};

/** «¿Te sirvió?» keeps one answer per reader and question: the match or the pick times 8, plus the question. */
const QUESTION_CODE: Readonly<Record<ExplainEntity, Partial<Record<ExplainIntent, number>>>> = {
  match: { no_pick: 1, forecast: 2, risks: 3 },
  pick: { risks: 4, caution: 5 },
  parlay: { probability: 6 },
};

export function voteSubjectId(
  entity: ExplainEntity,
  itemId: number | null,
  intent: ExplainIntent,
): number {
  return (itemId ?? 0) * 8 + (QUESTION_CODE[entity][intent] ?? 0);
}

/** What `explain_opened` records: the question only - with «.missing» when PrediGol lacked its data - never free text. */
export function trackWhat(entity: ExplainEntity, intent: ExplainIntent, answered: boolean): string {
  return `${entity}.${intent}${answered ? "" : ".missing"}`;
}

export function questionText(entity: ExplainEntity, intent: ExplainIntent): string {
  return t(`explain.question.${entity}.${intent}`);
}

function str(p: P, key: string): string | null {
  const v = p[key];
  return typeof v === "string" && v ? v : null;
}

function num(p: P, key: string): number | null {
  const v = p[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function strings(p: P, key: string): string[] {
  const v = p[key];
  return Array.isArray(v)
    ? v.filter((x): x is string => typeof x === "string" && x.length > 0)
    : [];
}

function numbers(p: P, key: string): number[] | null {
  const v = p[key];
  if (!Array.isArray(v) || v.length === 0) return null;
  const out = v.filter((x): x is number => typeof x === "number" && Number.isFinite(x));
  return out.length === v.length ? out : null;
}

function joinAnd(items: string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")}${t("match.facts.and")}${items[items.length - 1]}`;
}

/** A forecast's probability: whole points, as the reading writes it (52 %). */
function whole(v: number | null): string | null {
  return v === null ? null : fmtPct(v, 0);
}

/** A parlay's probability, with the digits it needs: 54,3 % · 0,42 % · < 0,01 % (the slip's own way). */
export function share(p: number | null): string {
  if (p === null) return DASH;
  if (p < 0.0001) return `< ${fmtPct(0.0001, 2)}`;
  return fmtPct(p, p < 0.01 ? 2 : 1);
}

function say(code: string, vars?: Record<string, string | number>): string {
  return t(`explain.say.${code}`, vars);
}

/** «Gana Nacional», «Más de 2,5 goles»: a selection of a forecast's market with the match's names. */
function selectionOf(p: P, selection: string): string {
  const line = num(p, "line");
  return selectionLabel({
    market_key: str(p, "market") ?? "",
    selection,
    line: line ?? 0,
    home: str(p, "home") ?? undefined,
    away: str(p, "away") ?? undefined,
  });
}

function forecastMarket(p: P): string | null {
  const market = str(p, "market");
  const selections = strings(p, "selections");
  const probabilities = numbers(p, "probabilities");
  if (!market || !probabilities || selections.length !== probabilities.length || !selections.length)
    return null;
  const likely = str(p, "likely");
  const all = selections.map((s, i) => ({
    s,
    text: `${selectionOf(p, s)} ${whole(probabilities[i] ?? null)}`,
  }));
  const label = marketName(market);
  const pct = whole(num(p, "p"));
  if (!likely || pct === null || !selections.includes(likely)) {
    return say("forecast_market_even", {
      market: label,
      others: all.map((x) => x.text).join(", "),
    });
  }
  return say("forecast_market", {
    market: label,
    likely: selectionOf(p, likely),
    pct,
    uncal: p["calibrated"] === false ? t("explain.uncalibrated") : "",
    others: all
      .filter((x) => x.s !== likely)
      .map((x) => x.text)
      .join(", "),
  });
}

function noValue(p: P): string | null {
  const evaluated = num(p, "evaluated");
  if (evaluated === null || evaluated < 1) return null;
  const parts = (["no_value", "odds", "market", "other"] as const)
    .map((k) => [k, num(p, k) ?? 0] as const)
    .filter(([, n]) => n > 0)
    .map(([k, n]) => `${t(`explain.part.${k}`)}${evaluated > 1 ? ` (${n})` : ""}`);
  return parts.length
    ? say("no_pick_no_value", { count: evaluated, parts: parts.join("; ") })
    : null;
}

function legLine(p: P): string | null {
  const leg = num(p, "leg");
  const market = str(p, "market");
  const selection = str(p, "selection");
  if (leg === null || !market || !selection) return null;
  const home = str(p, "home");
  const away = str(p, "away");
  const vars = {
    leg,
    match: home && away ? `${home} – ${away}` : t("explain.unknownMatch"),
    selection: selectionLabel({
      market_key: market,
      selection,
      line: num(p, "line") ?? 0,
      home: home ?? undefined,
      away: away ?? undefined,
    }),
  };
  const prob = num(p, "p");
  const source = str(p, "source");
  if (prob === null || (source !== "model" && source !== "market"))
    return say("parlay_leg_nodata", vars);
  return say("parlay_leg", { ...vars, pct: share(prob), source: t(`explain.source.${source}`) });
}

function reasonsText(p: P): string | null {
  const words = strings(p, "reasons")
    .map((r) => `explain.reason.${r}`)
    .filter((key) => hasKey(key))
    .map((key) => t(key));
  return words.length ? joinAnd(words) : null;
}

function issue(p: P): string | null {
  const code = str(p, "code");
  const leg = num(p, "leg");
  if (!code) return null;
  const fallback = leg === null ? say("parlay_invalid") : say("parlay_issue", { leg });
  return translateOr(`records.slip.error.${code}`, fallback, {
    leg: leg ?? undefined,
    with: num(p, "with") ?? undefined,
  });
}

/** The sentences without parameters: the template alone. */
const PLAIN = new Set([
  "pick_rule",
  "no_pick_published",
  "no_pick_past",
  "no_pick_no_forecast",
  "no_pick_no_prices",
  "no_pick_not_compared",
  "no_pick_may_change",
  "forecast_hidden",
  "forecast_what",
  "forecast_calibrated",
  "forecast_uncalibrated",
  "forecast_not_pick",
  "risks_hidden",
  "risks_intro",
  "risks_none",
  "risks_incomplete",
  "pick_reading_hidden",
  "pick_started",
  "caution_downgraded",
  "caution_none_approved",
  "caution_none_pending",
  "caution_none_not_reviewed",
  "caution_no_value",
  "caution_rejected",
  "caution_evaluation",
  "caution_what",
  "parlay_invalid",
  "parlay_single",
  "parlay_shrinks",
]);

function writers(): Record<string, (p: P) => string | null> {
  return {
    has_pick: (p) => {
      const count = num(p, "count");
      return count === null || count < 1 ? null : say("has_pick", { count });
    },
    no_pick_not_published: (p) => {
      const count = num(p, "evaluated");
      return count === null || count < 1 ? null : say("no_pick_not_published", { count });
    },
    no_pick_no_value: noValue,
    forecast_market: forecastMarket,
    pick_probability: (p) => {
      const pct = whole(num(p, "p"));
      return pct === null ? null : say("pick_probability", { pct });
    },
    pick_interval: (p) => {
      const low = whole(num(p, "low"));
      const high = whole(num(p, "high"));
      return low === null || high === null ? null : say("pick_interval", { low, high });
    },
    pick_review_risks: (p) => {
      const risks = strings(p, "risks");
      return risks.length ? say("pick_review_risks", { risks: risks.join("; ") }) : null;
    },
    parlay_issue: issue,
    parlay_all_win: (p) => {
      const legs = num(p, "legs");
      return legs === null || legs < 2 ? null : say("parlay_all_win", { legs });
    },
    parlay_leg: legLine,
    parlay_leg_missing: (p) => {
      const legs = strings(p, "legs");
      return legs.length
        ? say("parlay_leg_missing", { count: legs.length, legs: joinAnd(legs) })
        : null;
    },
    parlay_product: (p) => {
      const each = numbers(p, "probabilities");
      const all = num(p, "p");
      return !each || all === null
        ? null
        : say("parlay_product", { chain: each.map(share).join(" × "), pct: share(all) });
    },
    parlay_dependency: (p) => {
      const reasons = reasonsText(p);
      const all = num(p, "p");
      return reasons === null || all === null
        ? null
        : say("parlay_dependency", { reasons, pct: share(all) });
    },
    parlay_related: (p) => {
      const reasons = reasonsText(p);
      return reasons === null ? null : say("parlay_related", { reasons });
    },
    parlay_very_unlikely: (p) => {
      const all = num(p, "p");
      return all === null ? null : say("parlay_very_unlikely", { pct: share(all) });
    },
  };
}

/** The codes this page words: the ones with their own writer and the plain sentences. */
export function writtenSayCodes(): string[] {
  return [...Object.keys(writers()), ...PLAIN];
}

/** One line in the reader's language; null when the page cannot write it whole. */
export function lineText(line: ExplainLine): string | null {
  if (line.fact) return factText(line.fact);
  const code = line.say;
  if (!code) return null;
  if (PLAIN.has(code)) return hasKey(`explain.say.${code}`) ? say(code) : null;
  const write = writers()[code];
  return write ? write(line.params) : null;
}

/** The answer's sentences, in order, without the ones the page cannot write. */
export function answerLines(answer: Explanation): string[] {
  return answer.lines.map(lineText).filter((x): x is string => x !== null && x.length > 0);
}
