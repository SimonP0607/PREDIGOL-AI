/**
 * PREDIGOL INTELLIGENCE in words: a card's full title, its edge in percentage points, the "why" and "what could
 * go wrong" lines, the L1 brief's labels and the leg a card adds to "Mi parlay". Pure: no React, no fetching.
 *
 * The brief's notes and the review's claims are the owner's preview (or enforced); a user in shadow mode gets
 * neither, so every card also has plain lines built from its numbers alone - never an invented reason.
 */
import { intlTag, t, translateOr } from "@/lib/i18n";
import { fmtLine, fmtOdds, fmtPct, toNumber } from "@/lib/i18n/format";
import type { AiClaim, AnalysisCard, BriefView, MatchAnalysis } from "@/lib/api/v1/types_ai_layer";
import { normLine } from "@/product/records/model";
import { marketName, selectionLabel } from "@/product/shared/markets";
import { isParlayMarket, type NewLeg } from "@/product/odds/parlay";

export interface Sides {
  home: string;
  away: string;
}

type CardSelection = Pick<AnalysisCard, "market" | "selection" | "line">;

// ── the title ───────────────────────────────────────────────────────────────

/** "Resultado final (1X2)", "Goles: más/menos de 2,5", "Ambos marcan": the market a card is about. */
export function marketTitle(market: string, line: string | number | null | undefined): string {
  if (market === "OU") {
    const n = toNumber(line);
    return n === null
      ? marketName(market)
      : t("match.analysis.marketTitle.OU", { line: fmtLine(n) });
  }
  return translateOr(`match.analysis.marketTitle.${market}`, marketName(market));
}

/**
 * The selection once the market is named: "Gana Millonarios", "Más de 2,5", "Sí", "Millonarios −0,5",
 * "Millonarios o empate". Over/under and both-teams-score drop what the market title already says.
 */
export function selectionPhrase(card: CardSelection, sides: Sides): string {
  const n = toNumber(card.line);
  const line = n === null ? "" : card.market === "AH" ? fmtLine(n, true) : fmtLine(n);
  const label = selectionLabel({
    market_key: card.market,
    selection: card.selection,
    line: card.line,
    home: sides.home,
    away: sides.away,
  });
  return translateOr(`match.analysis.selectionPhrase.${card.market}.${card.selection}`, label, {
    line,
    home: sides.home,
    away: sides.away,
  });
}

/** "Resultado final (1X2) — Gana Millonarios": shown whole, whatever its length. */
export function cardTitle(card: CardSelection, sides: Sides): string {
  return t("match.analysis.cardTitle", {
    market: marketTitle(card.market, card.line),
    selection: selectionPhrase(card, sides),
  });
}

// ── figures ─────────────────────────────────────────────────────────────────

const ONE_DECIMAL = new Map<string, Intl.NumberFormat>();

/** A probability difference in percentage points, one decimal: 0.0745 -> "7,5" (signed: "+7,5"). */
function points(edge: number, signed: boolean): string {
  const key = `${intlTag()}|${signed}`;
  let f = ONE_DECIMAL.get(key);
  if (!f) {
    f = new Intl.NumberFormat(intlTag(), {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
      signDisplay: signed ? "exceptZero" : "auto",
    });
    ONE_DECIMAL.set(key, f);
  }
  // 0.0745 * 100 is 7.4499… in binary: settle the product first so a half rounds up, as on paper.
  return f.format(Number((edge * 100).toFixed(6)));
}

/**
 * An edge in percentage points, signed, with its unit apart so a figure can set it smaller:
 * 0.07 -> { value: "+7,0", unit: "pp" }. Null without an edge (the figure shows "—").
 */
export function ppParts(
  edge: string | number | null | undefined,
): { value: string; unit: string } | null {
  const n = toNumber(edge);
  return n === null ? null : { value: points(n, true), unit: t("match.analysis.ppUnit") };
}

// ── why, and what could go wrong ───────────────────────────────────────────

/** The words of a list of claims, blanks dropped. */
export function claimTexts(claims: readonly AiClaim[] | null | undefined): string[] {
  return (claims ?? [])
    .map((c) => (typeof c?.text === "string" ? c.text.trim() : ""))
    .filter((text) => text.length > 0);
}

/**
 * "¿Por qué?": the brief's notes, else the review's positives, else the numbers - PrediGol's estimate against
 * the market's and, when there is one, the edge over the market's fair price.
 */
export function whyLines(card: AnalysisCard): string[] {
  const notes = claimTexts(card.notes?.why);
  if (notes.length) return notes;
  const positives = claimTexts(card.ai?.positives);
  if (positives.length) return positives;

  const model = toNumber(card.p_model);
  const market = card.kind === "no_market" ? null : toNumber(card.p_market);
  const edge = card.kind === "no_market" ? null : toNumber(card.edge);
  const out: string[] = [];
  if (model !== null) {
    out.push(
      market !== null
        ? t("match.analysis.why.estimate", { model: fmtPct(model), market: fmtPct(market) })
        : t("match.analysis.why.estimateOnly", { model: fmtPct(model) }),
    );
  }
  if (edge !== null && edge > 0) {
    out.push(t("match.analysis.why.edge", { edge: points(edge, false) }));
  }
  const minimum = toNumber(card.minimum_odds);
  if (card.kind === "no_market" && minimum !== null) {
    out.push(t("match.analysis.why.minimum", { min: fmtOdds(minimum) }));
  }
  return out.length ? out : [t("match.analysis.why.none")];
}

/**
 * About how many times in ten the selection loses at PrediGol's probability: round((1 − p) × 10), half up,
 * never 0 (nothing is certain) and never 10 (it can win). Null without a probability.
 */
export function failsInTen(pModel: string | number | null | undefined): number | null {
  const p = toNumber(pModel);
  if (p === null || p < 0 || p > 1) return null;
  const n = Math.round(Number(((1 - p) * 10).toFixed(6)));
  return Math.min(9, Math.max(1, n));
}

/**
 * "¿Qué puede salir mal?": the brief's notes, else the review's risks, else honest variance from the numbers
 * (and, without an observed price, that its value cannot be confirmed).
 */
export function riskLines(card: AnalysisCard): string[] {
  const notes = claimTexts(card.notes?.risks);
  if (notes.length) return notes;
  const risks = claimTexts(card.ai?.risks);
  if (risks.length) return risks;

  const out: string[] = [];
  if (card.kind === "no_market") out.push(t("match.analysis.risk.noPrice"));
  const n = failsInTen(card.p_model);
  if (n !== null) out.push(t("match.analysis.risk.variance", { n }));
  return out.length ? out : [t("match.analysis.risk.none")];
}

// ── the brief (L1) ──────────────────────────────────────────────────────────

/** "Escrito por <modelo> (L1)" or "Escrito por las reglas". */
export function briefAuthor(brief: Pick<BriefView, "engine" | "model">): string {
  if (brief.engine === "rules") return t("match.analysis.brief.byRules");
  const model = brief.model?.trim();
  return t("match.analysis.brief.byModel", {
    model: model ? model : t("match.analysis.brief.aiModel"),
  });
}

/** Why the brief escalated the match, in words; an unknown code reads as its words. */
export function briefReason(code: string): string {
  return translateOr(`match.analysis.brief.reason.${code}`, code.replace(/_/g, " "));
}

/** A player's status as the brief wrote it, in the reader's language when it is a known one. */
export function injuryStatus(status: string | null | undefined): string {
  const raw = (status ?? "").trim();
  if (!raw) return "";
  const code = raw.toLowerCase().replace(/[\s-]+/g, "_");
  return /^[a-z_]+$/.test(code) ? translateOr(`match.analysis.brief.status.${code}`, raw) : raw;
}

/** "Millonarios · J. Pérez · duda". */
export function injuryLine(
  injury: { side: string; player: string; status: string | null | undefined },
  sides: Sides,
): string {
  const team =
    injury.side === "home" ? sides.home : injury.side === "away" ? sides.away : injury.side;
  const status = injuryStatus(injury.status);
  return status
    ? t("match.analysis.brief.injury", { team, player: injury.player, status })
    : t("match.analysis.brief.injuryNoStatus", { team, player: injury.player });
}

/** The newest of the analysis and its brief. */
export function analysisUpdatedAt(
  a: Pick<MatchAnalysis, "built_at" | "updated_at">,
): string | null {
  return a.updated_at ?? a.built_at ?? null;
}

// ── "Mi parlay" ─────────────────────────────────────────────────────────────

export interface CardMatch {
  fixture_id: number;
  kickoff_at: string;
  status_group?: string | null | undefined;
}

/** The leg a card adds: its best price, and PrediGol's probability for it (shown, never sent to a model). */
export function cardLeg(card: AnalysisCard, match: CardMatch, sides: Sides): NewLeg | null {
  if (card.kind === "no_market" || !isParlayMarket(card.market)) return null;
  return {
    fixture_id: match.fixture_id,
    market_key: card.market,
    selection: card.selection,
    line: normLine(card.line),
    home: sides.home,
    away: sides.away,
    kickoff_at: match.kickoff_at,
    odds: card.odds,
    bookmaker: card.bookmaker,
    p_model: card.p_model,
  };
}
