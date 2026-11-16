/// <reference types="bun" />
/**
 * The pieces of PrediGol Intelligence (UX-140): each says its state in words in both languages, prints the contract's
 * figure as it comes, and the private band is always on a private view.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import {
  CONFIRMATION,
  LIFECYCLE,
  PUBLIC_LIFECYCLE,
  clampShare,
  isConfirmation,
  isLifecycle,
} from "./model";
import {
  ConfirmationLevel,
  EntityHeader,
  EvaluationSteps,
  LifecycleChip,
  PrivateBand,
  ProbabilityLine,
  SourceLevelList,
  VersionHistory,
} from "./Pieces";

afterEach(() => setLocale("es"));

describe("the words of Intelligence", () => {
  test("every state and level has its words in Spanish and English", () => {
    for (const locale of ["es", "en"] as const) {
      const cat = CATALOGS[locale]["intelligence"] as Record<string, Record<string, string>>;
      for (const s of LIFECYCLE) expect(cat["lifecycle"]?.[s]).toBeTruthy();
      for (const c of CONFIRMATION) expect(cat["confirmation"]?.[c]).toBeTruthy();
    }
  });

  test("a reader only ever sees in play and settled", () => {
    expect([...PUBLIC_LIFECYCLE].sort()).toEqual(["in_play", "settled"]);
  });

  test("an unknown word is not a state", () => {
    expect(isLifecycle("shadow_confirmed")).toBe(true);
    expect(isLifecycle("rumour")).toBe(false);
    expect(isConfirmation("contradictory")).toBe(true);
    expect(isConfirmation(3)).toBe(false);
  });

  test("a share outside 0..1 is drawn inside it", () => {
    expect(clampShare(1.4)).toBe(1);
    expect(clampShare(-0.2)).toBe(0);
    expect(clampShare(Number.NaN)).toBe(0);
  });
});

describe("the pieces", () => {
  test("a state chip says the state in words, with an icon, not by colour alone", () => {
    const html = renderToStaticMarkup(<LifecycleChip state="awaiting_lineups" />);
    expect(html).toContain("Pendiente de alineaciones");
    expect(html).toContain('data-state="awaiting_lineups"');
    expect(html).toContain("<svg");
  });

  test("a rumour carries its level, never reads as a fact", () => {
    const html = renderToStaticMarkup(<ConfirmationLevel level="unconfirmed" />);
    expect(html).toContain("No confirmada");
    setLocale("en");
    expect(renderToStaticMarkup(<ConfirmationLevel level="contradictory" />)).toContain(
      "Contradictory",
    );
  });

  test("the probability prints the contract's figure with its seal", () => {
    const html = renderToStaticMarkup(
      <ProbabilityLine label="Arsenal W" value={0.588} calibration="calibrated" />,
    );
    expect(html).toContain("59");
    expect(html).toContain("Calibrada");
    expect(html).toContain('aria-valuenow="59"');
    const raw = renderToStaticMarkup(
      <ProbabilityLine label="Arsenal W" value={0.785} calibration="uncalibrated" />,
    );
    expect(raw).toContain("Sin calibrar");
    expect(raw).toContain("text-warning");
  });

  test("the four evaluations mark the current one", () => {
    const html = renderToStaticMarkup(
      <EvaluationSteps
        steps={[
          { key: "E1", state: "done" },
          { key: "E2", state: "current" },
          { key: "E3", state: "pending" },
          { key: "E4", state: "pending" },
        ]}
      />,
    );
    expect(html).toContain('aria-current="step"');
    expect(html).toContain("Alineación oficial");
  });

  test("versions are listed, none rewritten; no versions, no block", () => {
    expect(renderToStaticMarkup(<VersionHistory versions={[]} />)).toBe("");
    const html = renderToStaticMarkup(
      <VersionHistory
        versions={[
          {
            id: "2",
            label: "E2 · Por novedad",
            at: "2026-11-21T16:42:00Z",
            detail: "Entra la sanción",
          },
          { id: "1", label: "E1 · Primera lectura", at: "2026-11-20T01:30:00Z" },
        ]}
      />,
    );
    expect(html.indexOf("E2 · Por novedad")).toBeLessThan(html.indexOf("E1 · Primera lectura"));
  });

  test("facts are grouped by level and link to their source outside", () => {
    const html = renderToStaticMarkup(
      <SourceLevelList
        facts={[
          {
            id: "a",
            text: "Sancionado una fecha",
            level: "official",
            sources: [{ name: "Liga", url: "https://example.org/x" }],
          },
          { id: "b", text: "Viajó con 19", level: "single_source", sources: [{ name: "Agencia" }] },
        ]}
      />,
    );
    expect(html).toContain("Oficial");
    expect(html).toContain("Un solo medio");
    expect(html).toContain('rel="noopener noreferrer nofollow"');
  });

  test("the private band says it is private", () => {
    expect(renderToStaticMarkup(<PrivateBand />)).toContain("no visible para usuarios");
  });

  test("a player's head never shows a photo, only his initials", () => {
    const html = renderToStaticMarkup(<EntityHeader kind="player" name="James Rodríguez" />);
    expect(html).not.toContain("<img");
    expect(html).toContain("Jugador");
  });
});
