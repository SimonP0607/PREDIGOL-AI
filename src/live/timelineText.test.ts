/// <reference types="bun" />
/**
 * REVIEW PREDIGOL (11 Oct 2026), P0: the Cronología, the empty sections and the missing results
 * are said in the reader's language, with the right owner - never the API's English as is.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { sectionCodeText } from "@/components/system/LiveState";
import {
  resultWaitText,
  resultWaitTone,
  timelineDetail,
  timelineLabel,
  windowLabel,
} from "./timelineText";

describe("Cronología", () => {
  afterAll(() => setLocale("es"));

  test("a capture window is labelled by hours or minutes", () => {
    expect(windowLabel("1440")).toBe("24h");
    expect(windowLabel("30")).toBe("30m");
    expect(windowLabel(undefined)).toBe("");
  });

  test("a coded event is said in Spanish, with its values", () => {
    setLocale("es");
    const e = {
      key: "odds_1440",
      label: "Odds T-24h",
      detail: "asked at T-1438 min: the provider had no prices for this match",
      code: "window_provider_empty",
      vars: { window: "1440", minutes: "1438" },
    };
    expect(timelineLabel(e)).toBe("Cuotas T-24h");
    expect(timelineDetail(e)).toBe(
      "Consultado a T-1438 min: el proveedor no tenía cuotas para este partido",
    );
  });

  test("near-close off is by design, not a failure", () => {
    setLocale("es");
    expect(timelineDetail({ detail: "off by design", code: "near_close_off", vars: {} })).toContain(
      "Desactivada por diseño",
    );
  });

  test("the final pre-match outcome is translated too", () => {
    setLocale("en");
    expect(
      timelineDetail({
        detail: "read after the match: after_kickoff",
        code: "final_prematch_empty",
        vars: { outcome: "after_kickoff", quotes: "0", bookmakers: "0" },
      }),
    ).toBe(
      "Read after the match: the provider only had prices updated after kick-off (not usable as a close)",
    );
  });

  test("an event without a code, or with an unknown one, keeps the API's words", () => {
    setLocale("es");
    expect(timelineDetail({ detail: "something new", code: "brand_new_code", vars: {} })).toBe(
      "something new",
    );
    expect(timelineLabel({ key: "x", label: "Old label", code: null, vars: {} })).toBe("Old label");
  });
});

describe("empty sections", () => {
  afterAll(() => setLocale("es"));

  test("a known code is said in the reader's language; an unknown one is null", () => {
    setLocale("es");
    expect(sectionCodeText("lineups_not_published")).toBe(
      "El proveedor todavía no ha publicado las alineaciones.",
    );
    expect(sectionCodeText("not_a_code")).toBeNull();
    expect(sectionCodeText(null)).toBeNull();
  });
});

describe("missing results name their owner", () => {
  afterAll(() => setLocale("es"));

  test("the provider being late is a warning; our fault is negative", () => {
    expect(resultWaitTone("provider_pending")).toBe("warning");
    expect(resultWaitTone("provider_silent")).toBe("warning");
    expect(resultWaitTone("jobs_stalled")).toBe("negative");
    expect(resultWaitTone("provider_conflict")).toBe("negative");
    expect(resultWaitTone(null)).toBeNull();
  });

  test("the admin text carries the provider's status and the last read", () => {
    setLocale("es");
    const text = resultWaitText(
      { result_wait: "provider_pending", status_short: "INT" },
      "hace 12 min",
    );
    expect(text).toContain("«INT»");
    expect(text).toContain("hace 12 min");
    expect(text).toContain("No es un fallo nuestro");
    expect(resultWaitText({ result_wait: null, status_short: "FT" }, "")).toBeNull();
  });
});
