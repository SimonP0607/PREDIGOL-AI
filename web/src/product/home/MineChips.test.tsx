/// <reference types="bun" />
/**
 * The chips on a general pick card (plan de Inicio, 3.4): «Tu equipo», «Tu jugador», «Tu liga», «Tu mercado» - one for each
 * reason that applies, in that order, none when no favourite is in the pick.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { RelatedPick } from "@/lib/api/v1/types_me_today";
import { MineChips } from "./MineChips";

const pick = (over: Partial<RelatedPick>): RelatedPick => ({
  rank: 1,
  fixture_id: 100,
  market_key: "1X2",
  followed: null,
  market_followed: false,
  ...over,
});

function chips(related: RelatedPick): string[] {
  const markup = renderToStaticMarkup(<MineChips related={related} />);
  return [...markup.matchAll(/data-kind="(\w+)"/g)].map((m) => m[1]!);
}

describe("MineChips", () => {
  test("Spanish: each reason says itself", () => {
    setLocale("es");
    const markup = renderToStaticMarkup(
      <MineChips
        related={pick({
          followed: { kind: "team", names: ["Nacional"] },
          players: ["Uno"],
          market_followed: true,
        })}
      />,
    );
    for (const label of ["Tu equipo", "Tu jugador", "Tu mercado"]) expect(markup).toContain(label);
    expect(markup).not.toContain("Tu liga");
  });

  test("English", () => {
    setLocale("en");
    const markup = renderToStaticMarkup(
      <MineChips related={pick({ followed: { kind: "league", names: ["Liga BetPlay"] } })} />,
    );
    expect(markup).toContain("Your league");
    setLocale("es");
  });

  test("the order and the absence", () => {
    expect(
      chips(
        pick({
          followed: { kind: "team", names: ["A"] },
          players: ["B"],
          market_followed: true,
        }),
      ),
    ).toEqual(["team", "player", "market"]);
    expect(chips(pick({}))).toEqual([]);
    expect(renderToStaticMarkup(<MineChips related={pick({})} />)).toBe("");
  });
});
