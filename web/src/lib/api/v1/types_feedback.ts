/**
 * What readers think of PrediGol (plan UX, B6; section 40): the monthly survey, «¿Te sirvió?», Novedades read, and the
 * owner's view of them in /admin/product. Mirrors backend/src/fbi/api/contracts/feedback.py. The opinion improves the
 * product and never enters the models.
 */
import type { Iso } from "./types";

export type FeedbackSubject = "reading" | "narrative" | "explanation" | "explain";
export type FeedbackTrigger = "analysis_opened" | "result_seen";

/** Where it was asked, and nothing else: never a form's content. */
export interface FeedbackContext {
  trigger?: FeedbackTrigger | null;
  route?: string | null;
}

export interface SurveyState {
  /** FBI_FEEDBACK: false while the owner keeps the survey and the votes off. */
  enabled: boolean;
  /** Owed: on, the account past its first week, and no answer or skip in the last 30 days. */
  due: boolean;
  last_at: Iso | null;
  next_at: Iso | null;
}

export interface SurveyIn {
  /** «¿Qué tan útil te resultó PrediGol este mes?», 1 to 5. */
  score: number;
  comment?: string | null;
  context?: FeedbackContext;
}

export interface HelpfulIn {
  subject: FeedbackSubject;
  subject_id: number;
  helpful: boolean;
  context?: FeedbackContext;
}

export interface HelpfulVote {
  subject: FeedbackSubject;
  subject_id: number;
  /** The reader's answer; null while they have given none. */
  helpful: boolean | null;
}

export interface UpdatesSeen {
  /** The newest entry of Novedades the reader has seen; null: none. */
  last_seen: string | null;
}

export interface SurveyFigures {
  n: number;
  mean: number | null;
  /** Answers per score, "1" to "5". */
  scores: Record<string, number>;
  low: number;
  skipped: number;
}

export interface FeedbackOverview {
  enabled: boolean;
  since: Iso;
  survey: SurveyFigures;
  votes: Array<{ subject: FeedbackSubject; yes: number; no: number }>;
  /** The newest comments with their score and date - never who wrote them. */
  comments: Array<{ at: Iso; score: number; comment: string; trigger: FeedbackTrigger | null }>;
  /** Readers whose last survey of the last 30 days was 2 or less (EN RIESGO, B11). */
  at_risk: number;
}
