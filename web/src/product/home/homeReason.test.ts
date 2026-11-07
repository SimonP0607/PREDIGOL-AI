/// <reference types="bun" />
/** The words of the reasons the server chose for Inicio's «Partidos relevantes» and «Qué se juega» (plan de Inicio, 3.1b). */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import type { HomeReason } from "@/lib/api/v1/types_product";
import { reasonText } from "./homeReason";

setLocale("es");

const r = (code: HomeReason["code"], params: HomeReason["params"]): HomeReason => ({
  code,
  params,
});

describe("reasonText", () => {
  test("a final", () => {
    expect(reasonText(r("final", {}))).toBe("Es una final.");
  });

  test("a tie in play: who leads on aggregate, or that it is level", () => {
    const base = { home: "Greens", away: "Yellows", first_home: 0, first_away: 2 };
    expect(reasonText(r("tie", { ...base, agg_home: 1, agg_away: 2 }))).toBe(
      "Yellows va por delante en el global: 2-1.",
    );
    expect(reasonText(r("tie", { ...base, agg_home: 3, agg_away: 2 }))).toBe(
      "Greens va por delante en el global: 3-2.",
    );
    expect(reasonText(r("tie", { ...base, agg_home: 2, agg_away: 2 }))).toBe(
      "El global está igualado a 2.",
    );
  });

  test("a second leg to be played: how the first one ended, goal by side", () => {
    expect(
      reasonText(r("first_leg", { home: "Greens", away: "Yellows", first_home: 2, first_away: 2 })),
    ).toBe("Vuelta de la eliminatoria. En la ida: Greens 2, Yellows 2.");
  });

  test("a fight for the table, with and without how it is going", () => {
    expect(
      reasonText(
        r("stakes", { team: "Blues", side: "home", pressure: "relegation", state: "behind" }),
      ),
    ).toBe("Blues pelea por no descender y ahora pierde.");
    expect(reasonText(r("stakes", { team: "Reds", pressure: "title" }))).toBe(
      "Reds pelea el título.",
    );
    expect(
      reasonText(
        r("stakes", {
          team: "Reds",
          pressure: "title",
          other_team: "Blues",
          other_pressure: "europe",
        }),
      ),
    ).toBe("Reds pelea el título y Blues pelea plazas internacionales.");
  });

  test("a comeback, with its goal count in the singular and the plural", () => {
    expect(
      reasonText(r("comeback", { team: "Blues", side: "home", down_by: 1, state: "level" })),
    ).toBe("Blues iba perdiendo por 1 gol y ya empata.");
    expect(
      reasonText(r("comeback", { team: "Blues", side: "home", down_by: 2, state: "ahead" })),
    ).toBe("Blues iba perdiendo por 2 goles y ya gana.");
  });

  test("a reason without what its sentence needs, or one this client does not know, says nothing", () => {
    expect(reasonText(r("tie", { home: "Greens" }))).toBeNull();
    expect(reasonText(r("stakes", { team: "Reds", pressure: "mid_table" }))).toBeNull();
    expect(reasonText(r("comeback", { team: "Blues", down_by: 1, state: "behind" }))).toBeNull();
    expect(reasonText({ code: "other" as HomeReason["code"], params: {} })).toBeNull();
  });

  test("in English", () => {
    setLocale("en");
    try {
      expect(reasonText(r("final", {}))).toBe("It is a final.");
      expect(
        reasonText(r("stakes", { team: "Blues", pressure: "relegation", state: "level" })),
      ).toBe("Blues are fighting to avoid relegation and are level now.");
    } finally {
      setLocale("es");
    }
  });
});
