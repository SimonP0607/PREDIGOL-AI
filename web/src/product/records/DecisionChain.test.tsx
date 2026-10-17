/// <reference types="bun" />
/**
 * REVIEW PREDIGOL, point 1, rendered: a user sees only that the AI looked at the pick (and what it said); the model's
 * name, "No publicado" and "Liquidado" are the owner's - and "Liquidado" is nobody's (the result is at the card's
 * foot).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { DecisionChain } from "./DecisionChain";

setLocale("es");
const AI = { decision: "APPROVE" as const, mode: "shadow" as const, enforced: false, by_llm: true };

describe("the decision chain by audience (REVIEW point 1)", () => {
  test("a user: the AI step only - no model, no publication step, no 'Liquidado'", () => {
    const html = renderToStaticMarkup(
      <DecisionChain model="elo_ologit" ai={AI} aiLatest={null} evaluation={false} admin={false} />,
    );
    expect(html).toContain('data-audience="user"');
    expect(html).not.toContain("elo_ologit");
    expect(html).not.toMatch(/publicado/i);
    expect(html).not.toMatch(/liquidado/i);
    expect(html).toContain("IA: ");
    expect(html).toContain("confirmado");
  });

  test("a user and a pick the AI never looked at: nothing at all", () => {
    expect(
      renderToStaticMarkup(
        <DecisionChain
          model="elo_ologit"
          ai={null}
          aiLatest={null}
          evaluation={false}
          admin={false}
        />,
      ),
    ).toBe("");
  });

  test("the owner: the model, the AI and the publication step - still no 'Liquidado'", () => {
    const html = renderToStaticMarkup(
      <DecisionChain model="elo_ologit" ai={AI} aiLatest={null} evaluation admin />,
    );
    expect(html).toContain('data-audience="admin"');
    expect(html).toContain("elo_ologit");
    expect(html).not.toMatch(/liquidado/i);
  });
});
