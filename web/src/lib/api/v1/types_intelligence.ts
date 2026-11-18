/**
 * The base shapes every Intelligence contract is built from (backend `fbi.api.contracts.intelligence.base`, AD-J01).
 * A field without value is a `Missing` that says why; a probability always travels sealed (`Probability`): the web draws
 * `pct` as it comes and never recomputes, rounds otherwise, combines or chooses between probabilities.
 */

export type MissingReason =
  | "no_entregado"
  | "aun_no_disponible"
  | "sin_datos"
  | "sin_cobertura"
  | "reglamento_no_codificado"
  | "muestra_insuficiente"
  | "pendiente_derechos"
  | "retirado_por_derechos"
  | "sin_publicados"
  | "sin_resultados"
  | "sin_favoritos";

export interface Missing {
  missing_reason: MissingReason;
  expected_piece?: string;
  expected_at?: string;
  sample?: number;
  min_sample?: number;
}

export interface ItemList<T> {
  items: T[];
  missing_reason?: MissingReason;
  sample?: number;
  min_sample?: number;
}

export type Maybe<T> = T | Missing;

export function isMissing(v: unknown): v is Missing {
  return typeof v === "object" && v !== null && "missing_reason" in v;
}

/** The value when there is one, else null (the reason stays in the payload for whoever needs it). */
export function present<T>(v: Maybe<T> | undefined | null): T | null {
  return v === undefined || v === null || isMissing(v) ? null : (v as T);
}

export interface Freshness {
  generated_at: string;
  stale: boolean;
  stale_reason: string | null;
}

export type CalibrationSeal = "calibrada" | "sin_calibrar";

export interface Probability {
  value: number;
  pct: number;
  interval_pct: { low: number; high: number } | Missing;
  calibration: CalibrationSeal;
  as_of: string;
  evaluation: string | Missing;
  evaluation_version: number | Missing;
  origin: string;
}

export interface ContractHead {
  contract: string;
  contract_version: string;
  projection: "public" | "private";
  freshness: Freshness;
}

export type MarketState = "evaluable" | "en_calibracion" | "necesita_datos" | "no_ofrecer";
