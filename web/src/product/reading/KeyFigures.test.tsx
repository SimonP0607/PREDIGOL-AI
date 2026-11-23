/// <reference types="bun" />
/**
 * AP-P07 (a): the Análisis opens with its key figures and «Cómo quedaría la tabla», read from the facts the reading already
 * carries - so each figure must be the one its sentence says (checked over 20 matches), the sentences stay below, folded, and a
 * reading without such facts is shown exactly as before.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import type { Envelope } from "@/lib/api/v1/types";
import type { MatchReading, ReadingFact } from "@/lib/api/v1/types_reading";
import { ReadingView } from "./ReadingBlock";
import { factText } from "./text";
import { keyFigures } from "./figuresModel";
import type { ReadingLoad } from "./useReading";

setLocale("es");
afterEach(() => setLocale("es"));

const load = (data: MatchReading): ReadingLoad => ({
  status: "success",
  envelope: {
    status: "ok",
    data,
    reason: null,
    meta: { generated_at: "2026-10-25T12:00:00Z", api_version: "v1" },
  } as Envelope<MatchReading | null>,
});

/** A deterministic family of 20 matches: every figure changes with the index. */
function match(i: number): { reading: MatchReading; home: string; away: string } {
  const home = `Local ${i}`;
  const away = `Visita ${i}`;
  const seqs = ["WWWDW", "LDLWD", "WLWLW", "DDDWL", "WWLLD"];
  const facts: ReadingFact[] = [
    {
      code: "stakes_zone",
      params: { team: home, rank: 1 + (i % 6), zone: "europe" },
      ref: "packet:table",
    },
    {
      code: "stakes_gap_up",
      params: { team: away, gap: 1 + (i % 9), zone: "europe" },
      ref: "packet:table",
    },
    {
      code: "form",
      params: {
        team: home,
        sequence: seqs[i % 5] ?? "WWWDW",
        n: 5,
        ppg: 1 + (i % 3) * 0.5,
        goals_for: 1.5,
        goals_against: 0.8,
      },
      ref: "packet:form",
    },
    {
      code: "xg",
      params: { team: away, xg_for: 1 + i / 20, xg_against: 0.9 + i / 40, n: 6 },
      ref: "packet:xg",
    },
    { code: "rest_days", params: { team: home, days: 3 + (i % 5) }, ref: "packet:rest" },
    {
      code: "table_after",
      params: {
        result: "home_win",
        home,
        away,
        home_points: 30 + i,
        away_points: 20,
        home_best: 1,
        home_worst: 2,
        away_best: 5,
        away_worst: 5,
      },
      ref: "packet:table",
    },
    {
      code: "table_after",
      params: {
        result: "draw",
        home,
        away,
        home_points: 28 + i,
        away_points: 21,
        home_best: 2,
        home_worst: 2,
        away_best: 4,
        away_worst: 5,
      },
      ref: "packet:table",
    },
    {
      code: "table_after",
      params: {
        result: "away_win",
        home,
        away,
        home_points: 27 + i,
        away_points: 23,
        home_best: 3,
        home_worst: 4,
        away_best: 3,
        away_worst: 4,
      },
      ref: "packet:table",
    },
  ];
  return {
    home,
    away,
    reading: {
      fixture_id: i,
      version: "reading-v1",
      complete: true,
      data_at: "2026-10-25T10:30:00Z",
      forecast_at: null,
      sections: [{ key: "context", facts }],
    },
  };
}

describe("the key figures read from the facts", () => {
  test("20 matches: every figure is the one its sentence says", () => {
    for (let i = 0; i < 20; i++) {
      const { reading, home, away } = match(i);
      const f = keyFigures(reading, { home, away });
      expect(f).not.toBeNull();
      const facts = reading.sections[0]?.facts ?? [];
      const sentence = (code: string, team?: string) => {
        const fact = facts.find((x) => x.code === code && (!team || x.params["team"] === team));
        return fact ? (factText(fact) ?? "") : "";
      };
      // position: the sentence names it
      expect(sentence("stakes_zone", home)).toContain(`${f?.home.rank}`);
      // points to the zone
      expect(sentence("stakes_gap_up", away)).toContain(`${f?.away.gap?.points}`);
      // xG for and against, as the sentence writes them
      expect(sentence("xg", away)).toContain(localFixed(f?.away.xg?.for ?? NaN, 2));
      expect(sentence("xg", away)).toContain(localFixed(f?.away.xg?.against ?? NaN, 2));
      // days of rest
      expect(sentence("rest_days", home)).toContain(`${f?.home.rest?.days}`);
      // the form's letters are the sentence's letters
      const letters = (f?.home.form?.letters ?? []).map((l) => ({ W: "G", D: "E", L: "P" })[l]);
      expect(sentence("form", home)).toContain(letters.join(""));
      // the table: the three scenarios, with the sentence's points
      expect(f?.table.map((s) => s.result)).toEqual(["home_win", "draw", "away_win"]);
      for (const s of f?.table ?? []) {
        const text = factText(facts.find((x) => x.params["result"] === s.result) as ReadingFact);
        expect(text).toContain(`${s.homePoints}`);
        expect(text).toContain(`${s.awayPoints}`);
      }
    }
  });

  test("a side's missing figure leaves its place empty, never invented", () => {
    const { reading, home, away } = match(3);
    const only = {
      ...reading,
      sections: [
        {
          key: "context" as const,
          facts: (reading.sections[0]?.facts ?? []).filter((f) => f.code === "xg"),
        },
      ],
    };
    const f = keyFigures(only, { home, away });
    expect(f?.home.xg).toBeNull();
    expect(f?.away.xg).not.toBeNull();
    expect(f?.table).toEqual([]);
  });

  test("without any of these facts there are no key figures", () => {
    const f = keyFigures(
      { ...match(1).reading, sections: [{ key: "summary", facts: [] }] },
      { home: "A", away: "B" },
    );
    expect(f).toBeNull();
  });

  test("without the page's names the first two teams the facts name are the sides", () => {
    const { reading, home, away } = match(2);
    const f = keyFigures(reading);
    expect(f?.home.team).toBe(home);
    expect(f?.away.team).toBe(away);
  });
});

describe("the Análisis with key figures", () => {
  test("figures and table first, the sentences below and folded, all still there", () => {
    const { reading, home, away } = match(4);
    const html = renderToStaticMarkup(<ReadingView load={load(reading)} teams={{ home, away }} />);
    const figures = html.indexOf('data-testid="key-figures"');
    const folded = html.indexOf('data-testid="reading-sentences"');
    expect(figures).toBeGreaterThan(-1);
    expect(folded).toBeGreaterThan(figures);
    expect(html).toContain("<details");
    expect(html).toContain("Ver el análisis en frases");
    expect(html).toContain("Cifras clave");
    expect(html).toContain("Cómo quedaría la tabla");
    expect(html).toContain(`Si gana ${home}`);
    expect(html).toContain("Si empatan");
    expect(html).toContain(`Si gana ${away}`);
    // the sentences themselves are still in the page
    expect(html).toContain('data-code="form"');
  });

  test("a reading without those facts is shown as it was: no figures, no fold", () => {
    const html = renderToStaticMarkup(
      <ReadingView
        load={load({
          fixture_id: 9,
          version: "reading-v1",
          complete: true,
          data_at: "2026-10-25T10:30:00Z",
          forecast_at: null,
          sections: [
            {
              key: "summary",
              facts: [
                {
                  code: "match_intro",
                  params: { competition: "Liga BetPlay" },
                  ref: "packet:fixture",
                },
              ],
            },
          ],
        })}
      />,
    );
    expect(html).not.toContain('data-testid="key-figures"');
    expect(html).not.toContain("<details");
    expect(html).toContain("Liga BetPlay");
  });

  test("in English", () => {
    setLocale("en");
    const { reading, home, away } = match(4);
    const html = renderToStaticMarkup(<ReadingView load={load(reading)} teams={{ home, away }} />);
    expect(html).toContain("Key figures");
    expect(html).toContain("How the table would look");
    expect(html).toContain("If they draw");
  });
});
