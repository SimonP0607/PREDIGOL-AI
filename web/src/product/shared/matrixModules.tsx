/**
 * Cuotas, Picks, Noticias and Mi parlay read the availability matrix (plan PM, PM-14-04; UX-240): the ONE place where a module asks C-16
 * what it says of a match, so that four modules do not each reimplement the reading. Each module has its own line
 * (`Me.matrix_modules`: FBI_MATRIX_ODDS, _PICKS, _NEWS, _PARLAY), off by default:
 *
 * - `off`: nothing is read, nothing changes - the module decides as it always did;
 * - `show`: the module reads C-16 and only SAYS what it says - one note per screen, from the same components as «información no
 *   disponible» (`UnavailableNotes`); no price, pick, market or leg is added, hidden or changed;
 * - `on`: the matrix replaces the module's own check where this file says so (`hiddenMarkets` for Cuotas, `parlayAllowed` for Mi parlay);
 *   Picks and Noticias only say it - a pick that was published is never withdrawn because of a matrix.
 *
 * Nothing here decides a level or a verdict: it reads what `fbi.coverage.resolve` already decided (a market's three module verdicts, a
 * block's level). Pure but for the hooks and the note.
 */
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { live } from "@/lib/api/v1/queries";
import type { MatchOddsBook, OddsBookMarket } from "@/lib/api/v1/types_odds_explorer";
import type {
  AvailabilityModule,
  BlockAvailability,
  MarketAvailability,
  MatchAvailability,
} from "@/lib/api/v1/types_availability";
import type { MatrixMode, MatrixModule } from "@/lib/api/v1/types_auth";
import { present } from "@/lib/api/v1/types_intelligence";
import { useMatrixMode } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { catalogTarget, targetOfKey } from "@/product/match/marketLink";
import { blockUnavailable, moduleKind, type Unavailable } from "./availabilityState";
import { UnavailableNotes } from "./Unavailable";

/** The four modules, in the order the API lists them (`Me.matrix_modules`). */
export const MATRIX_MODULES: readonly MatrixModule[] = ["odds", "picks", "news", "parlay"];

/** The verdict of C-16 each module of the web reads (`MarketAvailability.modules`); Noticias reads blocks, not markets. */
export const VERDICT_OF: Record<MatrixModule, AvailabilityModule | null> = {
  odds: "cuotas",
  picks: "picks",
  parlay: "mi_parlay",
  news: null,
};

/** The blocks of a match page the press cards lean on (the absences cross-check the line-ups, the referee's cards the referee). */
export const NEWS_BLOCKS = ["lineups", "referee"] as const;

/**
 * What a module's «no» of one market means on screen, or null when the module takes it (or C-16 holds no verdict of it, which says
 * nothing). Cuotas fails at the price (state 3); Mi parlay and Picks at the rules of the module (state 7).
 */
export function verdictState(
  market: MarketAvailability,
  module: AvailabilityModule,
): Unavailable | null {
  const verdict = market.modules.find((m) => m.module === module);
  if (!verdict || verdict.ok) return null;
  return {
    kind: moduleKind(verdict.reason),
    step: module === "cuotas" ? "cuota" : "reglas",
    reason: verdict.reason,
    level: present(market.level),
    module,
  };
}

/**
 * A market of C-16 in words where the screen has no title of its own: the category of «Mercados» that holds it (a screen would
 * otherwise pile a raw key per market); null for a key the catalogue does not structure.
 */
export function categorySubject(market: MarketAvailability): string | null {
  const target = targetOfKey(market.key);
  return target ? t(`match.catalog.category.${target.category}`) : null;
}

/** The market of C-16 a market of Cuotas is (by the catalogue's key of its taxonomy key and period), or null when C-16 lists none. */
export function matrixMarketOf(
  availability: MatchAvailability | null,
  taxonomyKey: string,
  period: string,
): MarketAvailability | null {
  if (!availability) return null;
  const key = catalogTarget(taxonomyKey, period)?.key;
  if (!key) return null;
  return availability.markets.find((m) => m.key === key) ?? null;
}

/** The notes of one screen: a market per entry, its state under the module's verdict (only the ones the module refuses). */
export function marketEntries(
  availability: MatchAvailability | null,
  module: AvailabilityModule,
  subjectOf: (market: MarketAvailability) => string | null,
): Array<{ subject: string; state: Unavailable | null }> {
  const out: Array<{ subject: string; state: Unavailable | null }> = [];
  for (const m of availability?.markets ?? []) {
    const state = verdictState(m, module);
    const subject = state ? subjectOf(m) : null;
    if (state && subject) out.push({ subject, state });
  }
  return out;
}

/** The blocks Noticias leans on, as notes: only the ones the match does not have complete (A or B). */
export function blockEntries(
  blocks: readonly BlockAvailability[] | null | undefined,
  subjectOf: (key: string) => string,
): Array<{ subject: string; state: Unavailable | null }> {
  const out: Array<{ subject: string; state: Unavailable | null }> = [];
  for (const key of NEWS_BLOCKS) {
    const block = blocks?.find((b) => b.key === key);
    if (!block || block.reason === "sin_medir") continue;
    const state = blockUnavailable(block);
    if (state) out.push({ subject: subjectOf(key), state });
  }
  return out;
}

/**
 * Cuotas with the matrix on (`on` only): the keys, taxonomy key and period, of the markets C-16 lists whose price is not in force
 * (fewer than three houses): they stay out of the match's list. A market C-16 does not list stays - the matrix hides what it knows.
 */
export function hiddenMarkets(
  availability: MatchAvailability | null,
  mode: MatrixMode,
): ReadonlySet<string> {
  const hidden = new Set<string>();
  if (mode !== "on") return hidden;
  for (const m of availability?.markets ?? []) {
    if (m.modules.some((v) => v.module === "cuotas" && !v.ok)) hidden.add(m.key);
  }
  return hidden;
}

/**
 * Cuotas' book of a match as the matrix lets it be seen: with `on`, without the markets C-16 lists whose price is not in force; in any
 * other mode (and whenever C-16 has not answered) the book itself, the same object. A family left empty goes out with its markets.
 */
export function bookWithMatrix(
  book: MatchOddsBook | undefined,
  availability: MatchAvailability | null,
  mode: MatrixMode,
): MatchOddsBook | undefined {
  if (!book || mode !== "on" || !availability) return book;
  const hidden = hiddenMarkets(availability, mode);
  if (hidden.size === 0) return book;
  const kept = (m: OddsBookMarket) => {
    const key = catalogTarget(m.info.key, m.period)?.key;
    return !key || !hidden.has(key);
  };
  const families = book.families
    .map((f) => ({ ...f, markets: f.markets.filter(kept) }))
    .filter((f) => f.markets.length > 0);
  return { ...book, families };
}

/** Mi parlay with the matrix on: a selection C-14 says the server takes is also taken only if C-16 does not refuse the whole market. */
export function parlayAllowed(
  c14Allowed: boolean,
  market: MarketAvailability | null | undefined,
  mode: MatrixMode,
): boolean {
  if (!c14Allowed || mode !== "on" || !market) return c14Allowed;
  const verdict = market.modules.find((m) => m.module === "mi_parlay");
  return verdict ? verdict.ok : c14Allowed;
}

/** The reason C-16 gives for refusing a market to Mi parlay (its `mi_parlay` verdict), or null when it does not. */
export function parlayRefusal(market: MarketAvailability | null | undefined): string | null {
  const verdict = market?.modules.find((m) => m.module === "mi_parlay");
  return verdict && !verdict.ok ? verdict.reason : null;
}

/**
 * What C-16 says of a match for a module, or null while the module is off (nothing is asked) or C-16 has not answered. One request
 * per match, shared by the four modules (the query key is the match tab's own).
 */
export function useMatrixReading(
  module: MatrixModule,
  fixtureId: string | number | null | undefined,
): { mode: MatrixMode; availability: MatchAvailability | null } {
  const mode = useMatrixMode(module);
  const id = fixtureId === null || fixtureId === undefined ? "" : String(fixtureId);
  const q = useQuery({
    ...live.matchAvailability(id),
    enabled: mode !== "off" && id !== "",
    retry: false,
  });
  if (mode === "off") return { mode, availability: null };
  return { mode, availability: present(q.data?.data?.match) ?? null };
}

/**
 * The one note of a screen for a module (`show` and `on`): the markets the module refuses, or the blocks Noticias leans on, in the
 * five states of «información no disponible». Nothing while the module is off, while C-16 is silent or when there is nothing to say.
 */
export function MatrixNotes({
  module,
  fixtureId,
  subjectOf,
  only,
  blockName,
  className,
}: {
  module: MatrixModule;
  fixtureId: string | number | null | undefined;
  /** The words of a market of C-16 (its title on this screen); null leaves it out. */
  subjectOf?: (market: MarketAvailability) => string | null;
  /** Only the markets this says yes to (Picks: the pick's own market, not every market of the match). */
  only?: (market: MarketAvailability) => boolean;
  /** The words of a block (Noticias). */
  blockName?: (key: string) => string;
  className?: string;
}): ReactNode {
  const { mode, availability } = useMatrixReading(module, fixtureId);
  if (mode === "off" || !availability) return null;
  const verdict = VERDICT_OF[module];
  const entries =
    verdict !== null
      ? marketEntries(
          only ? { ...availability, markets: availability.markets.filter(only) } : availability,
          verdict,
          subjectOf ?? categorySubject,
        )
      : blockEntries(availability.blocks, blockName ?? ((k) => t(`availability.datum.${k}`)));
  if (entries.length === 0) return null;
  return (
    <div data-testid={`matrix-note-${module}`} data-mode={mode}>
      <UnavailableNotes entries={entries} className={className} />
    </div>
  );
}
