/// <reference types="bun" />
/**
 * Plan PM, PM-14-01 (I12): one component per state, each saying what happens and what still holds, with the words of the state and
 * never a «0», a bare «—» or the same message for two states; one note per screen; and the system's tokens they use read at AA.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { contrast, over, rootTokens } from "@/lib/a11y/contrast";
import {
  NotOffered,
  PartialCoverage,
  PendingData,
  ThinSample,
  UnavailableNotes,
  UnavailableNotice,
  UnderReview,
} from "./Unavailable";
import { listText, type Unavailable } from "./availabilityState";

afterAll(() => setLocale("es"));

const text = (html: string) =>
  html
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();

describe("the five states", () => {
  test("1 · not offered: one line, no card, the subjects joined with «ni»", () => {
    setLocale("es");
    const html = renderToStaticMarkup(<NotOffered subjects={["remates", "posesión", "córners"]} />);
    expect(text(html)).toBe("Esta competición no ofrece remates, posesión ni córners.");
    expect(html).not.toContain("card-surface");
    expect(html).toContain('data-unavailable="no_existe"');
    expect(renderToStaticMarkup(<NotOffered subjects={[]} />)).toBe("");
  });

  test("2 · pending: says when, and carries the screen's action", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <PendingData
        subject="Alineaciones"
        when="1 h antes: hacia las 17:30"
        action={<button type="button">Avisarme cuando salgan</button>}
      />,
    );
    expect(text(html)).toContain("Alineaciones: aún no disponible");
    expect(text(html)).toContain("Suele publicarse 1 h antes: hacia las 17:30.");
    expect(html).toContain("Avisarme cuando salgan");
    const price = text(renderToStaticMarkup(<PendingData subject="Córners" step="cuota" />));
    expect(price).toContain("al menos 3 casas");
  });

  test("3 · thin sample: the count and the distance to the minimum, never a rate", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <ThinSample subject="tarjetas y penaltis por partido" n={6} min={20} />,
    );
    const words = text(html);
    expect(words).toContain("Pocos datos");
    expect(words).toContain("Con 6, la cifra no dice nada.");
    expect(words).toContain("6 de 20 partidos");
    expect(words).toContain("faltan 14");
    expect(html).toContain('aria-label="6 de 20 partidos"');
    expect(words).not.toMatch(/\d+ ?%/);
  });

  test("4 · under review: a warning band with what still holds", () => {
    setLocale("es");
    const html = renderToStaticMarkup(
      <UnderReview
        subject="las estadísticas de este partido"
        why="Dos fuentes no coinciden en los remates."
      />,
    );
    expect(html).toContain('data-tone="warning"');
    expect(text(html)).toContain("Estamos revisando las estadísticas de este partido.");
    expect(text(html)).toContain("sigue valiendo");
    const probs = text(renderToStaticMarkup(<UnderReview subject="córners" step="autorizada" />));
    expect(probs).toContain("probabilidad implícita del mercado sigue valiendo");
  });

  test("partial coverage: the note with its percentage", () => {
    setLocale("es");
    const words = text(
      renderToStaticMarkup(<PartialCoverage subjects={["remates de jugador"]} pct={62} />),
    );
    expect(words).toContain("el dato llega en el 62 % de los partidos");
  });

  test("the dispatcher draws one component per state, and nothing when the datum is available", () => {
    setLocale("es");
    const kinds: Unavailable["kind"][] = [
      "no_existe",
      "cobertura_parcial",
      "muestra_insuficiente",
      "pendiente",
      "en_revision",
    ];
    const seen = new Set<string>();
    for (const kind of kinds) {
      const html = renderToStaticMarkup(
        <UnavailableNotice
          subject="córners"
          state={{ kind, step: "cobertura", reason: "x", n: 4, pct: 40 }}
        />,
      );
      expect(html).toContain(`data-unavailable="${kind}"`);
      seen.add(text(html));
    }
    expect(seen.size).toBe(kinds.length);
    expect(renderToStaticMarkup(<UnavailableNotice subject="córners" state={null} />)).toBe("");
    const settle = renderToStaticMarkup(
      <UnavailableNotice
        subject="el hándicap"
        state={{ kind: "no_existe", step: "liquidable", reason: "sin_regla" }}
      />,
    );
    expect(text(settle)).toContain("no se puede añadir a Mi parlay");
  });

  test("English has its own words", () => {
    setLocale("en");
    expect(text(renderToStaticMarkup(<NotOffered subjects={["shots", "corners"]} />))).toBe(
      "This competition does not offer shots or corners.",
    );
    expect(listText(["a", "b", "c"])).toBe("a, b and c");
    setLocale("es");
  });
});

describe("one note per screen", () => {
  test("a D league says each state once, its subjects together", () => {
    setLocale("es");
    const gone = { kind: "no_existe", step: "existe", reason: "no_entregado" } as const;
    const html = renderToStaticMarkup(
      <UnavailableNotes
        entries={[
          { subject: "remates", state: gone },
          { subject: "posesión", state: gone },
          { subject: "córners", state: gone },
          {
            subject: "árbitro",
            state: {
              kind: "muestra_insuficiente",
              step: "cobertura",
              reason: "muestra_insuficiente",
            },
          },
          { subject: "goles", state: null },
        ]}
      />,
    );
    const words = text(html);
    expect(words.match(/no ofrece/g)?.length).toBe(1);
    expect(words).toContain("remates, posesión ni córners");
    expect(words).toContain("Pocos datos de árbitro");
    expect(words).not.toContain("goles");
    expect(html).toContain('aria-label="Información no disponible en esta pantalla"');
    expect(
      renderToStaticMarkup(<UnavailableNotes entries={[{ subject: "goles", state: null }]} />),
    ).toBe("");
  });
});

describe("contrast (WCAG AA) of the tokens the states use", () => {
  const css = readFileSync(join(import.meta.dir, "..", "..", "styles.css"), "utf8");
  const tok = rootTokens(css);
  const solid = (name: string) => {
    const c = tok[name];
    if (!c) throw new Error(`no token ${name}`);
    return c.rgb;
  };
  const card = solid("card");
  const elevated = solid("elevated");
  const background = solid("background");
  // the warning band: warning at 9 % over a card (banner.tsx)
  const band = over({ rgb: solid("warning"), alpha: 0.09 }, card);
  // the neutral badge: foreground at 7 % over an elevated card (StatusBadge)
  const badge = over({ rgb: solid("foreground"), alpha: 0.07 }, elevated);

  test("text reads at 4.5:1 or more where each state puts it", () => {
    const pairs: Array<[string, number]> = [
      ["muted on background (one line)", contrast(solid("muted-foreground"), background)],
      ["muted on card", contrast(solid("muted-foreground"), card)],
      ["muted on elevated (pending, thin)", contrast(solid("muted-foreground"), elevated)],
      ["soft on elevated (thin body)", contrast(solid("foreground-soft"), elevated)],
      ["foreground on the warning band", contrast(solid("foreground"), band)],
      ["soft on the warning band", contrast(solid("foreground-soft"), band)],
      ["primary action on the warning band", contrast(solid("primary"), band)],
      ["the «Pocos datos» badge", contrast(solid("foreground-soft"), badge)],
    ];
    const low = pairs.filter(([, r]) => r < 4.5).map(([n, r]) => `${n}: ${r.toFixed(2)}`);
    expect(low).toEqual([]);
  });

  test("icons and the bar read at 3:1 or more (non-text contrast)", () => {
    const pairs: Array<[string, number]> = [
      ["warning icon on its band", contrast(solid("warning"), band)],
      ["info icon on card", contrast(solid("info"), card)],
      ["progress bar on elevated", contrast(solid("primary"), elevated)],
    ];
    const low = pairs.filter(([, r]) => r < 3).map(([n, r]) => `${n}: ${r.toFixed(2)}`);
    expect(low).toEqual([]);
  });
});
