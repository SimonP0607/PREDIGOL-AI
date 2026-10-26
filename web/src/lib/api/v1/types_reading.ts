/**
 * The structured reading of a match (plan UX, A9), as the API returns it. Mirrors fbi.api.contracts.reading: six sections of
 * facts, each a stable code with its parameters and a reference to where it comes from. The page writes every fact in the
 * reader's language from its own templates (src/product/reading) - and, when the API sends one, shows the narrative (A11):
 * the same sections written in Spanish and English by PrediGol's AI and checked sentence by sentence against these facts.
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

export interface NarrativeSentence {
  text: string;
  /** What it rests on: P:<block> (a fact of this reading) or E:<id> (a news item of the match). Never empty. */
  refs: string[];
}

export interface NarrativeSection {
  key: ReadingSectionKey;
  sentences: NarrativeSentence[];
}

export interface ReadingNarrative {
  version: string;
  /** When PrediGol's AI wrote it. */
  written_at: Iso;
  /** The moment of the data it was written from: «Escrito con datos de las 12:30». */
  data_at: Iso;
  es: NarrativeSection[];
  en: NarrativeSection[];
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
  /**
   * The narrative of THIS reading (A11), or null: none written for these facts, the owner keeps it off, or it failed its
   * checks - the facts above are then the whole reading. Older answers omit it.
   */
  narrative?: ReadingNarrative | null;
}
