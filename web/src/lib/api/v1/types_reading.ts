/**
 * The structured reading of a match (plan UX, A9), as the API returns it. Mirrors fbi.api.contracts.reading: six sections of
 * facts, each a stable code with its parameters and a reference to where it comes from. The page writes every fact in the
 * reader's language from its own templates (src/product/reading); no prose travels here.
 */
import type { Iso } from "./types";

export type ReadingSectionKey = "summary" | "context" | "data" | "market" | "risks" | "conclusion";
export type ReadingParam = string | number | boolean | string[] | null;

export interface ReadingFact {
  code: string;
  params: Record<string, ReadingParam>;
  /** packet:<block> (the match packet PrediGol Intelligence stored) or forecast:<market>. */
  ref: string;
}

export interface ReadingSection {
  key: ReadingSectionKey;
  facts: ReadingFact[];
}

export interface MatchReading {
  fixture_id: number;
  version: string;
  /** False: PrediGol has not gathered the match's context yet; the reading has the forecast and says so in its risks. */
  complete: boolean;
  data_at: Iso | null;
  forecast_at: Iso | null;
  /** In order; a section without facts is left out (risks never is). */
  sections: ReadingSection[];
}
