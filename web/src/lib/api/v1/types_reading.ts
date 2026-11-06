/**
 * The structured reading of a match (plan UX, A9), as the API returns it. Mirrors fbi.api.contracts.reading: six sections of
 * facts, each a stable code with its parameters and a reference to where it comes from. The page writes every fact in the
 * reader's language from its own templates (src/product/reading) - and, when the API sends one, shows the chronicle (A11,
 * UX-025): the story of the match - the lead, a paragraph for each side, the head-to-head and what could go wrong - written in
 * Spanish and English by PrediGol's AI and checked sentence by sentence against the match's facts and news.
 */
import type { Iso } from "./types";

/** The six sections of the structured reading. */
export type BaseSectionKey = "summary" | "context" | "data" | "market" | "risks" | "conclusion";
/** The six, then the three derived from them (UX-011): key points, why there is value, the factors that stand out. */
export type ReadingSectionKey = BaseSectionKey | "key_points" | "value" | "factors";
/** The sections of the chronicle, in order: the lead, a paragraph for each side, the head-to-head and the risks. */
export type NarrativeSectionKey = "summary" | "home" | "away" | "h2h" | "risks";
export type ReadingParam = string | number | boolean | string[] | null;

export interface ReadingFact {
  code: string;
  params: Record<string, ReadingParam>;
  /** packet:<block> (the match packet PrediGol Intelligence stored), forecast:<market> or pick:<id> (a pick PrediGol published). */
  ref: string;
}

export interface ReadingSection {
  key: ReadingSectionKey;
  facts: ReadingFact[];
}

export interface NarrativeSentence {
  text: string;
  /** What it rests on: P:<fact> (a fact of the match's story) or E:<id> (a news item of the match). Never empty. */
  refs: string[];
}

export interface NarrativeSection {
  key: NarrativeSectionKey;
  sentences: NarrativeSentence[];
}

/** The outlet of a piece of news the chronicle tells. */
export interface NarrativeSource {
  name: string;
}

export interface ReadingNarrative {
  version: string;
  /** When PrediGol's AI wrote it. */
  written_at: Iso;
  /** The moment of the data it was written from: «Escrito con datos de las 12:30». */
  data_at: Iso;
  /** In order: summary, home, away, h2h, risks - each only when the match has something to say there. */
  es: NarrativeSection[];
  en: NarrativeSection[];
  /** The outlets of the news it tells, once each («Fuentes»). Older answers omit it. */
  sources?: NarrativeSource[];
}

export interface MatchReading {
  fixture_id: number;
  version: string;
  /** False: PrediGol has not gathered the match's context yet; the reading has the forecast and says so in its risks. */
  complete: boolean;
  data_at: Iso | null;
  forecast_at: Iso | null;
  /**
   * In order: the six (a section without facts is left out, risks never is), then - each only when it has facts - the
   * derived ones: key_points, value, factors (UX-011). The narrative never reads those three.
   */
  sections: ReadingSection[];
  /**
   * The chronicle of THIS match's story (A11, UX-025), or null: none written for it yet, the owner keeps it off, or it failed
   * its checks - the facts above are then the whole reading. Older answers omit it.
   */
  narrative?: ReadingNarrative | null;
}
