/// <reference types="bun" />
/**
 * The monthly survey's card and «¿Te sirvió?» (plan UX, B6; section 40), without a browser: the scale is five radio
 * buttons with their words for a screen reader (the arrows move along it - e2e/feedback.spec.ts drives it with the
 * keyboard), the optional question follows the score (1-3 «¿Qué faltó?», 4-5 «¿Qué fue lo más útil?»), the comment asks
 * for no personal data and counts to 1,000, «Ahora no» and the cross close it in one tap, it is not modal; the vote names
 * what was read, says which answer is the reader's and, after a «No», offers to tell what was missing. And the owner's
 * card: the survey with its n, the CSAT, the scores, the votes and the comments without who wrote them.
 */
import { afterAll, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale, t } from "@/lib/i18n";
import type { FeedbackOverview } from "@/lib/api/v1/types_feedback";
import { FeedbackView } from "@/admin/FeedbackCard";
import { SMALL_SAMPLE, csat } from "@/admin/feedbackFigures";
import { CsatPromptView, type CsatPhase } from "./CsatPrompt";
import { COMMENT_MAX, SCORES, commentQuestion } from "./survey";
import { HelpfulVoteView } from "./HelpfulVote";

afterAll(() => setLocale("es"));

const noop = () => {};

function survey(phase: CsatPhase, score: number | null, comment = ""): string {
  return renderToStaticMarkup(
    <CsatPromptView
      phase={phase}
      score={score}
      comment={comment}
      onScore={noop}
      onComment={noop}
      onSend={noop}
      onSkip={noop}
      onClose={noop}
    />,
  );
}

async function routed(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/matches/7"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

/** The opening tag of the element with this test id. */
function tag(out: string, testId: string): string {
  return new RegExp(`<[a-z]+[^>]*data-testid="${testId}"[^>]*>`).exec(out)?.[0] ?? "";
}

describe("the monthly survey", () => {
  test("the question, a scale of five radio buttons with their words, closed in one tap; not modal", () => {
    setLocale("es");
    const out = survey("ask", null);
    expect(out).toContain("¿Qué tan útil te resultó PrediGol este mes?");
    expect(tag(out, "csat-prompt")).toContain('role="dialog"');
    expect(tag(out, "csat-prompt")).toContain('aria-modal="false"');
    expect([...out.matchAll(/type="radio"/g)]).toHaveLength(5);
    expect([...out.matchAll(/name="csat-score"/g)]).toHaveLength(5);
    expect(SCORES).toEqual([1, 2, 3, 4, 5]);
    expect(out).toContain("1 de 5: Nada útil");
    expect(out).toContain("5 de 5: Muy útil");
    expect(out).toContain("<legend");
    expect(out).not.toContain('data-testid="csat-comment"'); // the comment waits for a score
    expect(tag(out, "csat-send")).toMatch(/ disabled=""/);
    expect(out).toContain("Ahora no");
    expect(tag(out, "csat-close")).toContain('aria-label="Cerrar la encuesta"');
    // every target at least 44 px: the scale, «Ahora no», «Enviar»
    for (const id of ["csat-score-1", "csat-skip", "csat-send"])
      expect(tag(out, id)).toContain("min-h-11");
    expect(out).toContain(t("support.feedback.survey.note"));
  });

  test("the optional question follows the score: what was missing (1-3), what was most useful (4-5)", () => {
    setLocale("es");
    expect([1, 2, 3, 4, 5].map(commentQuestion)).toEqual([
      "missing",
      "missing",
      "missing",
      "best",
      "best",
    ]);
    const low = survey("ask", 2);
    expect(low).toContain("¿Qué faltó?");
    expect(low).not.toContain("¿Qué fue lo más útil?");
    expect(tag(low, "csat-score-2")).toContain('data-checked="true"');
    expect(low).toMatch(/<input(?=[^>]*checked="")(?=[^>]*value="2")[^>]*>/);
    const high = survey("ask", 5, "Las lecturas");
    expect(high).toContain("¿Qué fue lo más útil?");
    expect(tag(high, "csat-comment")).toMatch(new RegExp(`maxlength="${COMMENT_MAX}"`, "i"));
    expect(high).toContain("Sin datos personales");
    expect(high).toContain(`12 de ${COMMENT_MAX}`);
    expect(tag(high, "csat-send")).not.toMatch(/ disabled=""/);
  });

  test("a failed send says so and keeps the answer; the thanks lead to Novedades", async () => {
    setLocale("es");
    const failed = survey("failed", 4, "Muy claro");
    expect(tag(failed, "csat-error")).toContain('role="alert"');
    expect(failed).toContain("Muy claro");
    const thanks = await routed(
      <CsatPromptView
        phase="thanks"
        score={4}
        comment=""
        onScore={noop}
        onComment={noop}
        onSend={noop}
        onSkip={noop}
        onClose={noop}
      />,
    );
    expect(thanks).toContain("¡Gracias!");
    expect(tag(thanks, "csat-updates")).toContain('href="/updates"');
    expect(thanks).not.toContain('type="radio"');
  });

  test("in English too", () => {
    setLocale("en");
    const out = survey("ask", 3);
    expect(out).toContain("How useful was PrediGol to you this month?");
    expect(out).toContain("3 of 5: Somewhat useful");
    expect(out).toContain("What was missing?");
    expect(out).toContain("Not now");
  });
});

describe("«¿Te sirvió?»", () => {
  const vote = (props: Partial<Parameters<typeof HelpfulVoteView>[0]> = {}) =>
    renderToStaticMarkup(
      <HelpfulVoteView subject="reading" value={null} onVote={noop} {...props} />,
    );

  test("it names what was read, and neither answer is the reader's until they give one", () => {
    setLocale("es");
    const out = vote();
    expect(out).toContain("¿Te sirvió este análisis?");
    expect(tag(out, "helpful-vote")).toContain('data-vote="none"');
    expect(tag(out, "helpful-yes")).toContain('aria-pressed="false"');
    expect(tag(out, "helpful-no")).toContain('aria-pressed="false"');
    expect(tag(out, "helpful-yes")).toContain("min-h-11");
    expect(out).toContain('role="group"');
    expect(tag(out, "helpful-note")).toContain('aria-live="polite"');
    expect(vote({ subject: "narrative" })).toContain("¿Te sirvió este análisis?");
    expect(vote({ subject: "explanation" })).toContain("¿Te sirvió esta explicación?");
    expect(vote({ subject: "explain" })).toContain("¿Te sirvió esta respuesta?");
  });

  test("the reader's answer is pressed and thanked; after a «No», the way to tell what was missing", () => {
    setLocale("es");
    const yes = vote({ value: true });
    expect(tag(yes, "helpful-yes")).toContain('aria-pressed="true"');
    expect(tag(yes, "helpful-vote")).toContain('data-vote="yes"');
    expect(yes).toContain(t("support.feedback.helpful.thanks"));
    expect(yes).not.toContain('data-testid="helpful-tell-us"');
    const no = vote({ value: false, onTellUs: noop });
    expect(tag(no, "helpful-no")).toContain('aria-pressed="true"');
    expect(no).toContain("Cuéntanos qué faltó");
    expect(vote({ value: false })).not.toContain('data-testid="helpful-tell-us"'); // messages to PrediGol off
    expect(vote({ failed: true })).toContain(t("support.feedback.helpful.failed"));
    expect(tag(vote({ pending: true }), "helpful-yes")).toMatch(/ disabled=""/);
  });
});

const OVERVIEW: FeedbackOverview = {
  enabled: true,
  since: "2026-07-29T12:00:00Z",
  survey: {
    n: 12,
    mean: 3.9166,
    scores: { "1": 1, "2": 1, "3": 2, "4": 3, "5": 5 },
    low: 2,
    skipped: 4,
  },
  votes: [
    { subject: "reading", yes: 7, no: 3 },
    { subject: "explanation", yes: 2, no: 0 },
  ],
  comments: [
    {
      at: "2026-10-26T15:00:00Z",
      score: 2,
      comment: "Me faltó la Liga BetPlay",
      trigger: "result_seen",
    },
    { at: "2026-10-25T15:00:00Z", score: 5, comment: "Las lecturas", trigger: null },
  ],
  at_risk: 1,
};

describe("the owner's card", () => {
  test("the survey with its n, the mean, the CSAT (4 and 5) and each score; small samples said so", async () => {
    setLocale("es");
    expect(csat(OVERVIEW)).toBeCloseTo(8 / 12, 6);
    expect(csat({ ...OVERVIEW, survey: { ...OVERVIEW.survey, n: 0 } })).toBeNull();
    const out = renderToStaticMarkup(<FeedbackView o={OVERVIEW} />);
    expect(out).toMatch(/data-testid="feedback-n"[\s\S]*?>12</);
    expect(out).toContain("3,9");
    expect(out).toMatch(/data-testid="feedback-csat"[\s\S]*?67\s%/);
    expect([...out.matchAll(/data-score="(\d)"/g)].map((m) => m[1])).toEqual([
      "5",
      "4",
      "3",
      "2",
      "1",
    ]);
    expect(OVERVIEW.survey.n).toBeLessThan(SMALL_SAMPLE);
    expect(out).toContain('data-testid="feedback-small"');
    expect(out).toMatch(/data-testid="feedback-at-risk"[\s\S]*?>1</);
  });

  test("«¿Te sirvió?» per kind and the comments with their score and date - never who wrote them", () => {
    setLocale("es");
    const out = renderToStaticMarkup(<FeedbackView o={OVERVIEW} />);
    expect(out).toContain("Análisis (datos)");
    expect(out).toMatch(/70\s%/);
    expect(out).toContain("Me faltó la Liga BetPlay");
    expect(out).toContain("tras ver un resultado");
    expect([...out.matchAll(/data-testid="feedback-comment"/g)]).toHaveLength(2);
    expect(out).not.toMatch(/@|user_id|email/i);
  });

  test("off says the answers stay; nothing yet says so", () => {
    setLocale("es");
    const off = renderToStaticMarkup(
      <FeedbackView
        o={{
          ...OVERVIEW,
          enabled: false,
          survey: { n: 0, mean: null, scores: {}, low: 0, skipped: 0 },
          votes: [],
          comments: [],
        }}
      />,
    );
    expect(off).toContain("las respuestas se conservan");
    expect(off).toContain('data-testid="feedback-empty"');
    expect(off).not.toContain('data-testid="feedback-scores"');
  });
});
