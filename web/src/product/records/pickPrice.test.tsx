/// <reference types="bun" />
/**
 * The price on a pick of the day (plan AP-K05, decision D4): the price now in big with its hour, the published one small
 * beside it, «A este precio ya no hay valor» only when the expected value at the price now is not positive, an old price
 * never as the current one; and the history keeps the price of publication.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { DailyItem, PriceNow } from "@/lib/api/v1/types_records";
import { PickPriceColumn } from "./PickPriceColumn";
import { pickPrice } from "./pickPrice";
import { restatesFigures, whyLines } from "./cardWhy";

setLocale("es");
afterEach(() => setLocale("es"));

const now = (odds: string, freshness: PriceNow["freshness"] = "fresh"): PriceNow => ({
  odds,
  as_of: "2026-11-23T15:00:00Z",
  freshness,
  change: null,
});
const item = (odds: string, pNow: PriceNow | null, p = "0.60"): DailyItem =>
  ({ odds, p_model: p, price_now: pNow }) as DailyItem;

function text(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

describe("which price is in big", () => {
  test("the price now, with the one of publication aside and how far it moved", () => {
    const p = pickPrice(item("1.47", now("1.41")));
    expect(p).toMatchObject({ shown: "1.41", current: true, published: "1.47", delta: -0.06 });
    expect(pickPrice(item("1.47", now("1.52"))).delta).toBe(0.05);
    expect(pickPrice(item("1.47", now("1.47"))).delta).toBe(0);
  });

  test("an old price is never the current one: the published price stays in big", () => {
    const p = pickPrice(item("1.47", now("1.41", "stale")));
    expect(p).toMatchObject({ shown: "1.47", current: false, delta: null, noValue: false });
    expect(p.now?.freshness).toBe("stale");
  });

  test("no price now (settled, started, older answer): the published price, as before", () => {
    expect(pickPrice(item("1.47", null))).toMatchObject({ shown: "1.47", current: false });
    expect(pickPrice({ odds: "1.47", p_model: "0.6" })).toMatchObject({ shown: "1.47" });
  });

  test("«ya no hay valor» only when PrediGol's probability times the price now does not exceed 1", () => {
    // 0.60 × 1.66 = 0.996: no value at this price
    expect(pickPrice(item("1.80", now("1.66"))).noValue).toBe(true);
    // 0.60 × 1.70 = 1.02: still positive
    expect(pickPrice(item("1.80", now("1.70"))).noValue).toBe(false);
    expect(pickPrice(item("1.80", now("1.66", "stale"))).noValue, "an old price says nothing").toBe(
      false,
    );
  });
});

describe("the price column", () => {
  const column = (it: DailyItem, settled = false) =>
    renderToStaticMarkup(<PickPriceColumn item={it} settled={settled} compact={false} />);

  test("«Cuota actual», «Publicado a 1,47 · ▼ 0,06» and its hour", () => {
    const html = column(item("1.47", now("1.41"), "0.80"));
    const words = text(html);
    expect(words).toContain("1,41");
    expect(words).toContain("Cuota actual");
    expect(words).toContain("Publicado a 1,47");
    expect(words).toContain("▼ 0,06");
    expect(html).toContain('aria-label="bajó 0,06"');
    expect(html).not.toContain('data-testid="pick-no-value"');
  });

  test("it says when the price now has no value, and in English too", () => {
    expect(text(column(item("1.80", now("1.66"))))).toContain("A este precio ya no hay valor");
    setLocale("en");
    const words = text(column(item("1.80", now("1.66"))));
    expect(words).toContain("Current odds");
    expect(words).toContain("Published at 1.80");
    expect(words).toContain("At this price there is no longer value");
  });

  test("without a price now it is the reference price, the published one, as before", () => {
    const words = text(column(item("1.47", null), true));
    expect(words).toContain("1,47");
    expect(words).toContain("Cuota de referencia");
    expect(words).not.toContain("Publicado a");
  });
});

describe("the figures once and the reason that is not the figures", () => {
  const ai = (positives: string[], risks: string[] = []) =>
    ({
      ai: { decision: "APPROVE", mode: "enforce", enforced: true, positives, risks },
    }) as DailyItem;

  test("a positive that only repeats the two percentages is replaced by the rule's sentence", () => {
    expect(restatesFigures("Modelo 73.7 % frente a mercado 66.6 %")).toBe(true);
    expect(restatesFigures("Llega con cinco partidos sin perder")).toBe(false);
    expect(whyLines(ai(["Modelo 73.7 % frente a mercado 66.6 %"]))).toEqual([
      "PrediGol ve este resultado más probable que el mercado.",
    ]);
  });

  test("a rumour or a text in another script is not drawn; a decimal gets the language's comma", () => {
    expect(whyLines(ai(["Según rumores, el delantero no jugaría"]))).toEqual([
      "PrediGol ve este resultado más probable que el mercado.",
    ]);
    expect(whyLines(ai(["Marca 1.8 goles por partido"]))).toEqual(["Marca 1,8 goles por partido"]);
    expect(whyLines(ai(["Llega bien"], ["شائعات عن إصابة"]))).toEqual(["Llega bien"]);
  });
});
