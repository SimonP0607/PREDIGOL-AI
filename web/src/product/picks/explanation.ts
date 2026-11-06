/**
 * «¿Por qué PrediGol eligió este pick?» (plan UX, B3; section 28): the lines of the five layers, written from the API's values
 * with the reader's templates - nothing here is prose that came from the server, but for the validated narrative (A11), which
 * is shown as it was checked.
 *
 *   1 conclusion  what PrediGol expects, in one sentence (PrediGol's probability against the market's)
 *   2 context     the chronicle's sides and head-to-head, or the reading's facts, each with its reference
 *   3 market      the price it was published at, the best price now and whether it still has value
 *   4 risks       how often a selection like this fails, the model's doubt, the reading's risks and, only while the AI's
 *                 review is applied, the review's own
 *   5 how         the steps of «Cómo se decide» - the same as Transparencia - and whether it is a pick of the day
 */
import { getLocale, t } from "@/lib/i18n";
import { fmtOdds, fmtPct, toNumber } from "@/lib/i18n/format";
import { formatDateTime, formatTime } from "@/lib/time";
import type { PickExplanation } from "@/lib/api/v1/types_explanation";
import type { NarrativeSectionKey } from "@/lib/api/v1/types_reading";
import { factText } from "@/product/reading/text";
import { failsInTen } from "@/product/match/intelligence";
import { selectionLabel } from "@/product/shared/markets";

export const LAYERS = ["conclusion", "context", "market", "risks", "how"] as const;
export type Layer = (typeof LAYERS)[number];

/** «Cómo se decide»: every pick of the day passes these, in this order - the same list Transparencia shows. */
export const HOW_STEPS = ["model", "value", "risk", "context", "one"] as const;

/** «Nacional gana», «Más de 2,5 goles»: the selection in the reader's words. */
export function selectionOf(e: PickExplanation): string {
  return selectionLabel({
    market_key: e.market_key,
    selection: e.selection,
    line: e.line,
    home: e.match.home.name,
    away: e.match.away.name,
  });
}

/** Layer 1, one sentence: PrediGol's probability, against the market's when there is one. */
export function conclusionText(e: PickExplanation): string {
  const vars = { selection: selectionOf(e), p: fmtPct(e.market.p_model, 0) };
  return e.market.p_market === null
    ? t("picks.why.conclusion.alone", vars)
    : t("picks.why.conclusion.text", { ...vars, market: fmtPct(e.market.p_market, 0) });
}

/** The validated narrative's sentences of these sections, in the page's language; empty without a narrative. */
export function narrativeSentences(
  e: PickExplanation,
  keys: readonly NarrativeSectionKey[],
): string[] {
  if (!e.narrative) return [];
  const sections = getLocale() === "es" ? e.narrative.es : e.narrative.en;
  return keys.flatMap((k) =>
    (sections.find((s) => s.key === k)?.sentences ?? []).map((s) => s.text),
  );
}

/** Layer 2: the chronicle's two sides and head-to-head when there is one; otherwise the reading's facts. */
export function contextLines(e: PickExplanation): string[] {
  const narrative = narrativeSentences(e, ["home", "away", "h2h"]);
  if (narrative.length) return narrative;
  return e.context.flatMap((f) => {
    const text = factText(f);
    return text ? [text] : [];
  });
}

/** Why layer 2 is empty, when it is: the reading is hidden, or PrediGol has not gathered the match's context yet. */
export function contextEmptyText(e: PickExplanation): string {
  if (!e.reading_shown) return t("picks.why.context.hidden");
  return e.reading_complete ? t("picks.why.context.none") : t("picks.why.context.notYet");
}

/** Layer 3, after the two probabilities: the published price, the best price now and whether it still has value. */
export function marketLines(e: PickExplanation): string[] {
  const m = e.market;
  const published = m.published_bookmaker
    ? t("picks.why.market.publishedAt", {
        odds: fmtOdds(m.published_odds),
        bookmaker: m.published_bookmaker,
        when: formatDateTime(m.published_at),
      })
    : t("picks.why.market.published", {
        odds: fmtOdds(m.published_odds),
        when: formatDateTime(m.published_at),
      });
  const out = [published];
  if (e.started) {
    out.push(t("picks.why.market.started"));
    return out;
  }
  if (m.odds_now !== null) {
    out.push(
      m.bookmaker_now
        ? t("picks.why.market.nowAt", { odds: fmtOdds(m.odds_now), bookmaker: m.bookmaker_now })
        : t("picks.why.market.now", { odds: fmtOdds(m.odds_now) }),
    );
  } else {
    out.push(t("picks.why.market.noPriceNow"));
  }
  out.push(m.value_now ? t("picks.why.market.valueNow") : t("picks.why.market.noValueNow"));
  return out;
}

/** Layer 4: how often it fails, the model's doubt, then the chronicle's risks or the reading's facts. */
export function riskLines(e: PickExplanation): string[] {
  const out: string[] = [];
  const n = failsInTen(e.market.p_model);
  if (n !== null) out.push(t("match.analysis.risk.variance", { n }));
  const low = toNumber(e.market.p_low);
  const high = toNumber(e.market.p_high);
  if (low !== null && high !== null && high > low) {
    out.push(t("picks.why.risks.interval", { low: fmtPct(low, 0), high: fmtPct(high, 0) }));
  }
  const narrative = narrativeSentences(e, ["risks"]);
  if (narrative.length) return [...out, ...narrative];
  for (const f of e.risks) {
    const text = factText(f);
    if (text) out.push(text);
  }
  return out;
}

/**
 * Layer 5's line about this pick: a pick of the day passed every step; one of the list passes the value rule now (or did when
 * it was taken); a candidate in evaluation does not pass the first step.
 */
export function howText(e: PickExplanation): string {
  if (e.user_status === "EVALUATION") return t("picks.why.how.evaluation");
  if (e.day) return t("picks.why.how.dayPick", { rank: e.day.rank });
  if (e.started) return t("picks.why.how.taken");
  return e.market.value_now ? t("picks.why.how.listPick") : t("picks.why.how.noValue");
}

/** The line of a pick of the day: its rank, when it was chosen and at what price (the evaluation set's, in the preview). */
export function dayText(e: PickExplanation): string | null {
  const day = e.day;
  if (!day) return null;
  const vars = { rank: day.rank, time: formatTime(day.selected_at), odds: fmtOdds(day.odds) };
  return day.user_status === "EVALUATION"
    ? t("picks.why.dayEvaluation", vars)
    : t("picks.why.day", vars);
}
