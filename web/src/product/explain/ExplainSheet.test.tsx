/// <reference types="bun" />
/**
 * «Explícame» (plan UX, B9): the answer in the reader's words with its states - an answer, «No tengo ese dato» when PrediGol
 * lacks what the question needs, the words worth a tap and the places to read more. The button and its switch are proved
 * by the e2e (explain.spec.ts), which has a session.
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
import type { Explanation } from "@/lib/api/v1/types_explain";
import { setLocale } from "@/lib/i18n";
import { AnswerView } from "./ExplainSheet";

afterAll(() => setLocale("es"));

async function inRouter(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function answer(over: Partial<Explanation> = {}): Explanation {
  return {
    version: "explain-v1",
    entity: "match",
    item_id: 7,
    intent: "no_pick",
    answered: true,
    lines: [
      { say: "no_pick_published", params: {}, fact: null },
      { say: "pick_rule", params: {}, fact: null },
    ],
    terms: ["pick", "edge", "not_a_term_of_the_glossary"],
    links: ["transparency", "glossary"],
    ...over,
  };
}

describe("the answer", () => {
  test("its sentences, its words and the places to read more", async () => {
    setLocale("es");
    const html = await inRouter(<AnswerView answer={answer()} transparency />);
    expect(html).toContain('data-testid="explain-lines"');
    expect(html).toContain("PrediGol no publicó ningún pick de este partido.");
    expect(html).toContain("nunca inventa un pick para llenar el espacio");
    expect(html).not.toContain('data-testid="explain-no-data"');
    // only terms of the glossary become words to tap
    expect(html).toContain('data-testid="explain-terms"');
    expect(html).not.toContain("not_a_term_of_the_glossary");
    expect(html).toContain('data-testid="explain-link-transparency"');
    expect(html).toContain('data-testid="explain-link-glossary"');
  });

  test("«Cómo le va a PrediGol» only when it is open to the account", async () => {
    setLocale("es");
    const html = await inRouter(<AnswerView answer={answer()} />);
    expect(html).not.toContain('data-testid="explain-link-transparency"');
    expect(html).toContain('data-testid="explain-link-glossary"');
  });

  test("when PrediGol lacks the data it says so, with what is missing", async () => {
    setLocale("es");
    const html = await inRouter(
      <AnswerView
        answer={answer({
          answered: false,
          intent: "forecast",
          lines: [{ say: "forecast_hidden", params: {}, fact: null }],
        })}
      />,
    );
    expect(html).toContain('data-testid="explain-no-data"');
    expect(html).toContain("No tengo ese dato");
    expect(html).toContain("no muestra ahora su pronóstico");
    expect(html).toContain('data-answered="false"');
  });

  test("a line the page cannot write whole is left out, not shown raw", async () => {
    setLocale("es");
    const html = await inRouter(
      <AnswerView
        answer={answer({
          lines: [
            { say: "a_code_from_the_future", params: {}, fact: null },
            { say: "pick_rule", params: {}, fact: null },
          ],
        })}
      />,
    );
    expect(html).not.toContain("a_code_from_the_future");
    expect(html).not.toContain("explain.say");
    expect(html.match(/<li/g)?.length).toBeGreaterThanOrEqual(1);
  });

  test("a pick's answer links to «¿Por qué este pick?»; a match's does not", async () => {
    setLocale("es");
    const pick = await inRouter(
      <AnswerView
        answer={answer({
          entity: "pick",
          item_id: 41,
          intent: "caution",
          links: ["why_pick", "glossary"],
        })}
      />,
    );
    expect(pick).toContain('data-testid="explain-why-pick"');
    const match = await inRouter(<AnswerView answer={answer({ links: ["why_pick"] })} />);
    expect(match).not.toContain('data-testid="explain-why-pick"');
  });

  test("«Otra pregunta» only when messages to PrediGol are on, and the vote slot", async () => {
    setLocale("es");
    const without = await inRouter(<AnswerView answer={answer()} />);
    expect(without).not.toContain('data-testid="explain-other"');
    const withIt = await inRouter(
      <AnswerView
        answer={answer()}
        onOther={() => undefined}
        footer={<p data-testid="vote">v</p>}
      />,
    );
    expect(withIt).toContain('data-testid="explain-other"');
    expect(withIt).toContain("Otra pregunta");
    expect(withIt).toContain('data-testid="vote"');
  });

  test("English", async () => {
    setLocale("en");
    const html = await inRouter(<AnswerView answer={answer()} transparency />);
    expect(html).toContain("PrediGol did not publish any pick for this match.");
    expect(html).toContain("Glossary");
  });
});
