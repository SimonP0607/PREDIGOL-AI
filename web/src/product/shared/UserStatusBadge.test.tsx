/// <reference types="bun" />
/**
 * The visible state of a pick (plan UX, B3): the four states of the one table, each in words and with an icon - never colour
 * alone -, and «Revisión de contexto aún no aplicada» only beside a RECOMMENDED by the value rule alone.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { PickState, UserStatus } from "@/lib/api/v1/types_product";
import { setLocale } from "@/lib/i18n";
import { UserStatusBadge } from "./UserStatusBadge";
import { USER_STATUSES, reasonText, statusText } from "./userStatus";

const state = (user_status: UserStatus, context_pending = false): PickState => ({
  user_status,
  status_reason: user_status === "EVALUATION" ? "evaluation" : "value",
  context_pending,
});

afterAll(() => setLocale("es"));

describe("the state of a pick", () => {
  test("each state reads in words, with an icon, in Spanish and English", () => {
    const words = {
      es: {
        RECOMMENDED: "Recomendado",
        CAUTION: "Cautela",
        NOT_RECOMMENDED: "No recomendado",
        EVALUATION: "En evaluación",
      },
      en: {
        RECOMMENDED: "Recommended",
        CAUTION: "Caution",
        NOT_RECOMMENDED: "Not recommended",
        EVALUATION: "Being evaluated",
      },
    } as const;
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const s of USER_STATUSES) {
        const html = renderToStaticMarkup(<UserStatusBadge state={state(s)} />);
        expect(statusText(s)).toBe(words[locale][s]);
        expect(html).toContain(words[locale][s]);
        expect(html).toContain(`data-status="${s}"`);
        expect(html).toMatch(/<svg[^>]*aria-hidden="true"/);
      }
    }
  });

  test("the four states never share a colour, and the reading never needs one", () => {
    setLocale("es");
    const classes = USER_STATUSES.map((s) => {
      const html = renderToStaticMarkup(<UserStatusBadge state={state(s)} />);
      return (
        /class="(inline-flex items-center gap-1\.5 rounded border[^"]*)"/.exec(html)?.[1] ?? ""
      );
    });
    expect(new Set(classes).size).toBe(4);
  });

  test("the pending line goes only with a recommendation by the value rule alone", () => {
    setLocale("es");
    expect(renderToStaticMarkup(<UserStatusBadge state={state("RECOMMENDED", true)} />)).toContain(
      "Revisión de contexto aún no aplicada",
    );
    expect(
      renderToStaticMarkup(<UserStatusBadge state={state("RECOMMENDED", false)} />),
    ).not.toContain("pick-status-pending");
    expect(
      renderToStaticMarkup(
        <UserStatusBadge state={state("RECOMMENDED", true)} pendingNote={false} />,
      ),
    ).not.toContain("pick-status-pending");
    for (const s of ["CAUTION", "NOT_RECOMMENDED", "EVALUATION"] as const) {
      expect(renderToStaticMarkup(<UserStatusBadge state={state(s, true)} />)).not.toContain(
        "pick-status-pending",
      );
    }
  });

  test("an answer without a known state shows no badge at all", () => {
    setLocale("es");
    const unknown = { status_reason: "value", context_pending: true } as unknown as PickState;
    expect(renderToStaticMarkup(<UserStatusBadge state={unknown} />)).toBe("");
    const odd = { ...state("RECOMMENDED", true), user_status: "MAYBE" } as unknown as PickState;
    expect(renderToStaticMarkup(<UserStatusBadge state={odd} />)).toBe("");
  });

  test("every reason has its sentence in both languages", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const r of [
        "approved",
        "value",
        "not_reviewed",
        "downgraded",
        "rejected",
        "no_value_now",
        "evaluation",
      ] as const) {
        const text = reasonText(r);
        expect(text.length).toBeGreaterThan(20);
        expect(text).not.toContain("picks.status");
      }
    }
  });
});
