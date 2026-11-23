/**
 * The review of the 14 checks for the charts of the reader's statistics (plan Correcciones UX, AP-T03; FE-004), made on
 * 23 Nov 2026 against `stats/*`: the texts of the drawings are 12 px or more (`readerReview.test.tsx` reads the sources to keep it
 * so), colour is never the only signal (a number or a word sits beside every mark), every chart has its table or list for a screen
 * reader, nothing blinks or animates, the intervals are said in the reading sentence, and the buttons of the intervals and the view
 * switch of the radar are real buttons. If one of those stops being true, the test fails and this review has to be redone.
 */
import { CHART_CHECKS, type ChartCheck, type ChartReview } from "./evidence";

export const READER_REVIEW: ChartReview = {
  checks: Object.fromEntries(CHART_CHECKS.map((c): [ChartCheck, "ok"] => [c, "ok"])) as Record<
    ChartCheck,
    "ok"
  >,
  reviewedBy: "revisión de AP-T03",
  reviewedOn: "2026-11-23",
};
