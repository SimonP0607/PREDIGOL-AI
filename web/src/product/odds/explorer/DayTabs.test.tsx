/// <reference types="bun" />
/** «Hoy · Mañana · Pasado mañana» (AP-C01): the tabs, their counts and the way to the next day with prices. */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { DayTabs, dayLabel, nextDayWithPrices } from "./DayTabs";
import type { OddsDay } from "./model";

const DAYS: OddsDay[] = [
  { key: "today", bogota_date: "2026-11-23", fixtures: 0 },
  { key: "tomorrow", bogota_date: "2026-11-24", fixtures: 12 },
  { key: "day_after", bogota_date: "2026-11-25", fixtures: 3 },
];

describe("the next day with prices", () => {
  test("the first day after the one on show that has matches", () => {
    expect(nextDayWithPrices("today", DAYS)?.key).toBe("tomorrow");
    expect(nextDayWithPrices("tomorrow", DAYS)?.key).toBe("day_after");
    expect(nextDayWithPrices("day_after", DAYS)).toBeNull();
  });

  test("an old link's hours look from today; days still loading offer nothing", () => {
    expect(nextDayWithPrices(48, DAYS)?.key).toBe("tomorrow");
    expect(nextDayWithPrices("today", undefined)).toBeNull();
    expect(
      nextDayWithPrices(
        "today",
        DAYS.map((d) => ({ ...d, fixtures: 0 })),
      ),
    ).toBeNull();
  });
});

describe("the tabs", () => {
  const render = (value: Parameters<typeof DayTabs>[0]["value"], days = DAYS) =>
    renderToStaticMarkup(<DayTabs value={value} days={days} onChange={() => undefined} />);

  test("three days in order, each with its count for the eye and for a screen reader", () => {
    const markup = render("tomorrow");
    expect(markup.indexOf("Hoy")).toBeLessThan(markup.indexOf("Mañana"));
    expect(markup.indexOf("Mañana")).toBeLessThan(markup.indexOf("Pasado mañana"));
    expect(markup).toContain(", 12 partidos");
    expect(markup).toContain(", 3 partidos");
    expect(markup).toContain(", 0 partidos");
    expect(markup).toMatch(/aria-checked="true"[^>]*data-testid="odds-day-tomorrow"/);
  });

  test("while the counts load the names stand alone; an old link's hours leave every tab off", () => {
    const loading = renderToStaticMarkup(
      <DayTabs value="today" days={undefined} onChange={() => undefined} />,
    );
    expect(loading).toContain("Hoy");
    expect(loading).not.toContain("partidos");
    expect(render(null)).not.toContain('aria-checked="true"');
  });

  test("the labels", () => {
    expect(["today", "tomorrow", "day_after"].map((d) => dayLabel(d as never))).toEqual([
      "Hoy",
      "Mañana",
      "Pasado mañana",
    ]);
  });
});
