/**
 * «Información no disponible» (plan PM, PM-14-01, lámina I12; UX-173): which of five honest states a datum, a block or a market of
 * C-16 is in when it cannot be shown, and the first of C-16's seven states that failed. Pure but for `listText`, which joins words in the reader's language: the words are in the `availability`
 * namespace and the drawing in `Unavailable.tsx`. Nothing here decides what a module shows - it reads what C-16 already decided.
 *
 * The seven states of C-16 are evaluated in order; after the first «no» the next ones are not evaluated (`fbi.coverage.resolve`):
 *  1 existe · 2 cobertura suficiente · 3 cuota vigente · 4 probabilidad calculada · 5 calibrada y autorizada · 6 liquidable ·
 *  7 cumple las reglas del módulo (Mi parlay, Picks, Cuotas).
 * Each failure lands in one of the screen's states (section 4 of the plan; I12):
 *  - `no_existe`: the competition does not offer it - the block disappears, one line and no card;
 *  - `cobertura_parcial`: level C - drawn with the note «cobertura parcial» and its percentage;
 *  - `muestra_insuficiente`: there are data, but few - the count, never a rate;
 *  - `pendiente`: it will come (a price, a forecast, a line-up) - say when, and offer what is possible;
 *  - `en_revision`: it exists but is not reliable now (a model under evaluation, sources that disagree) - withdrawn and said.
 */
import type {
  AvailabilityModule,
  BlockAvailability,
  CoverageLevel,
  LevelCell,
  MarketAvailability,
  ModuleReason,
} from "@/lib/api/v1/types_availability";
import { isMissing, type Maybe } from "@/lib/api/v1/types_intelligence";
import { t } from "./availabilityText";

/** C-16's seven states, in the order they are evaluated. */
export const AVAILABILITY_STEPS = [
  "existe",
  "cobertura",
  "cuota",
  "probabilidad",
  "autorizada",
  "liquidable",
  "reglas",
] as const;
export type AvailabilityStep = (typeof AVAILABILITY_STEPS)[number];

/** The five states a screen draws (I12 and the plan's section 4); one component each. */
export const UNAVAILABLE_KINDS = [
  "no_existe",
  "cobertura_parcial",
  "muestra_insuficiente",
  "pendiente",
  "en_revision",
] as const;
export type UnavailableKind = (typeof UNAVAILABLE_KINDS)[number];

export interface Unavailable {
  kind: UnavailableKind;
  /** The first of the seven states that failed. */
  step: AvailabilityStep;
  /** C-16's reason, as it came (`no_entregado`, `sin_regla`, `MERCADO_NO_EVALUABLE`…). */
  reason: string;
  level?: CoverageLevel | null | undefined;
  /** Matches measured / with the datum (a cell or a block). */
  n?: number | undefined;
  /** Share of matches with the datum, 0-100, when C-16 gives it. */
  pct?: number | null | undefined;
  /** The module whose rules failed (state 7). */
  module?: AvailabilityModule | undefined;
}

/** The evaluation of one row: each of the seven states as «sí», «no» or «sin evaluar» (after the first «no»), for the console. */
export type StepResult = "si" | "no" | "sin_evaluar";

function value<T>(v: Maybe<T> | null | undefined): T | null {
  return v === null || v === undefined || isMissing(v) ? null : v;
}

/** A datum or block that was not delivered: gone for good, coming later or too few matches to say. */
function absentKind(reason: string, level: CoverageLevel | null): UnavailableKind {
  if (reason === "muestra_insuficiente" || level === "MI") return "muestra_insuficiente";
  if (reason === "sin_medir" || reason === "sin_ventana") return "pendiente";
  return "no_existe";
}

/** A datum that arrives but whose cell is under B: partial coverage, a thin sample, or none worth drawing. */
function coverageKind(reason: string, level: CoverageLevel | null): UnavailableKind {
  if (reason === "muestra_insuficiente" || level === "MI") return "muestra_insuficiente";
  if (reason === "sin_medir") return "pendiente";
  if (reason === "sin_cobertura") return "no_existe";
  if (level === "C" || level === "D") return "cobertura_parcial";
  return "no_existe";
}

/**
 * A block of a match page (`MatchAvailability.blocks`): null when it can be drawn complete (A or B); otherwise its state.
 * A block is the worst of its data (`fbi.coverage.resolve.BLOCKS`).
 */
export function blockUnavailable(block: BlockAvailability): Unavailable | null {
  const level = value(block.level);
  if (!block.exists) {
    return {
      kind: absentKind(block.reason, level),
      step: "existe",
      reason: block.reason,
      level,
      n: block.n,
    };
  }
  if (level === "A" || level === "B") {
    return block.reason === "muestra_insuficiente"
      ? { kind: "muestra_insuficiente", step: "cobertura", reason: block.reason, level, n: block.n }
      : null;
  }
  return {
    kind: coverageKind(block.reason, level),
    step: "cobertura",
    reason: block.reason,
    level,
    n: block.n,
  };
}

/** A cell of a competition (`SeasonAvailability.data` / `.markets`): null at A or B with its sample; otherwise its state. */
export function cellUnavailable(cell: LevelCell): Unavailable | null {
  const pct = value(cell.pct);
  if (cell.level === "A" || cell.level === "B") {
    return cell.reason === "muestra_insuficiente"
      ? {
          kind: "muestra_insuficiente",
          step: "cobertura",
          reason: cell.reason,
          level: cell.level,
          n: cell.n,
          pct,
        }
      : null;
  }
  if (
    cell.with_data === 0 &&
    cell.reason !== "sin_medir" &&
    cell.reason !== "muestra_insuficiente"
  ) {
    return {
      kind: "no_existe",
      step: "existe",
      reason: cell.reason,
      level: cell.level,
      n: cell.n,
      pct,
    };
  }
  return {
    kind: coverageKind(cell.reason, cell.level),
    step: "cobertura",
    reason: cell.reason,
    level: cell.level,
    n: cell.n,
    pct,
  };
}

/** What a module's «no» means on screen: a price still to come, a model under review, or a selection that cannot be. */
export function moduleKind(reason: ModuleReason): UnavailableKind {
  switch (reason) {
    case "market_not_priced":
    case "menos_de_3_casas":
    case "sin_precio":
      return "pendiente";
    case "MERCADO_NO_EVALUABLE":
    case "SIN_PROBABILIDAD":
    case "outlier_price":
    case "error_interno":
      return "en_revision";
    default:
      return "no_existe";
  }
}

/** The seven states of one market, «sí» up to the first «no» and «sin evaluar» after it (I11, «los siete estados»). */
export function marketSteps(
  market: MarketAvailability,
  module?: AvailabilityModule,
): Record<AvailabilityStep, StepResult> {
  const verdicts = market.modules.filter((m) => module === undefined || m.module === module);
  const answers: Record<AvailabilityStep, boolean> = {
    existe: market.exists,
    cobertura: value(market.coverage_ok) === true,
    cuota: market.price_in_force,
    probabilidad: market.prob_computed,
    autorizada: market.prob_authorised,
    liquidable: market.settleable,
    reglas: verdicts.length > 0 && verdicts.every((m) => m.ok),
  };
  const out = {} as Record<AvailabilityStep, StepResult>;
  let failed = false;
  for (const step of AVAILABILITY_STEPS) {
    if (failed) out[step] = "sin_evaluar";
    else if (answers[step]) out[step] = "si";
    else {
      out[step] = "no";
      failed = true;
    }
  }
  return out;
}

/** The first state that failed, or null when the market passes the seven. */
export function firstFailingStep(
  market: MarketAvailability,
  module?: AvailabilityModule,
): AvailabilityStep | null {
  const steps = marketSteps(market, module);
  return AVAILABILITY_STEPS.find((s) => steps[s] === "no") ?? null;
}

/**
 * A market of a match (`MatchAvailability.markets`): null when it passes the seven states (for `module`, or for every module);
 * otherwise the screen's state of the first one that failed.
 */
export function marketUnavailable(
  market: MarketAvailability,
  module?: AvailabilityModule,
): Unavailable | null {
  const step = firstFailingStep(market, module);
  if (step === null) return null;
  const level = value(market.level);
  const base = { step, level, reason: market.reason };
  switch (step) {
    case "existe":
      return { ...base, kind: absentKind(market.reason, level) };
    case "cobertura":
      return { ...base, kind: coverageKind(market.reason, level) };
    case "cuota":
    case "probabilidad":
      return { ...base, kind: "pendiente" };
    case "autorizada":
      return { ...base, kind: "en_revision" };
    case "liquidable":
      return { ...base, kind: "no_existe" };
    case "reglas": {
      const failed = market.modules.find(
        (m) => (module === undefined || m.module === module) && !m.ok,
      );
      const reason = failed?.reason ?? "invalid_selection";
      return { ...base, kind: moduleKind(reason), reason, module: failed?.module };
    }
  }
}

export interface UnavailableGroup {
  kind: UnavailableKind;
  /** The subjects (already in words) of the same state, in the order they came. */
  subjects: string[];
  items: Unavailable[];
}

/**
 * One note per state and per screen (risk of the card: a D league would otherwise pile a notice per block). Keeps the order of
 * the five states, and inside each one the order the subjects came in; a subject named twice is said once.
 */
export function groupUnavailable(
  entries: ReadonlyArray<{ subject: string; state: Unavailable | null }>,
): UnavailableGroup[] {
  const groups = new Map<UnavailableKind, UnavailableGroup>();
  for (const { subject, state } of entries) {
    if (!state) continue;
    const group = groups.get(state.kind) ?? { kind: state.kind, subjects: [], items: [] };
    if (!group.subjects.includes(subject)) group.subjects.push(subject);
    group.items.push(state);
    groups.set(state.kind, group);
  }
  return UNAVAILABLE_KINDS.flatMap((k) => {
    const g = groups.get(k);
    return g ? [g] : [];
  });
}

/** «a, b y c» (or «a, b ni c» after a negation), in the reader's language. */
export function listText(items: readonly string[], negative = false): string {
  if (items.length <= 1) return items[0] ?? "";
  const last = t(negative ? "availability.list.lastNegative" : "availability.list.last");
  return `${items.slice(0, -1).join(t("availability.list.sep"))}${last}${items[items.length - 1]}`;
}
