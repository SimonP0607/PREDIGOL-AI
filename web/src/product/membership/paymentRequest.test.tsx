/// <reference types="bun" />
/**
 * The reader's «ya pagué» (UX-091): what the form sends, when the page shows the owner's data and when it shows nothing,
 * the wait while the owner verifies, and what a refusal or an annulment says. Nothing is shown that the server did not send.
 */
import { afterAll, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import type { MyPaymentRequests, PaymentRequestView } from "@/lib/api/v1/types_payment_requests";
import { setLocale, t } from "@/lib/i18n";
import { PaymentRequestBody } from "./PaymentRequestPanel";
import {
  amountOf,
  bogotaDay,
  emptyForm,
  lastOutcome,
  mayPay,
  problems,
  toBody,
  type PayForm,
} from "./paymentRequest";

afterAll(() => setLocale("es"));

const NOW = new Date("2026-11-10T15:00:00Z");

function request(extra: Partial<PaymentRequestView> = {}): PaymentRequestView {
  return {
    id: 7,
    status: "submitted",
    expected_amount: "150000.00",
    currency: "COP",
    discount_percent: null,
    declared_amount: "150000.00",
    declared_paid_on: "2026-11-10",
    method: "nequi",
    reference_last4: "4567",
    payer_name: null,
    note: null,
    terms_version: "2026-11-10",
    accepted_at: "2026-11-10T15:00:00Z",
    created_at: "2026-11-10T15:00:00Z",
    decided_at: null,
    decision_code: null,
    decision_note: null,
    due_on: "2026-11-11",
    due_at: "2026-11-12T05:00:00Z",
    annulled: false,
    ...extra,
  };
}

function view(extra: Partial<MyPaymentRequests> = {}): MyPaymentRequests {
  return {
    available: true,
    locks: [],
    pay: { holder: "Titular de Prueba", breb_key: "@predigol-prueba", has_qr: true },
    price: { currency: "COP", amount: "150000", expected: "150000", discount_percent: null },
    terms: { version: "2026-11-10", sha256: "a".repeat(64), draft: false },
    whatsapp: "573016355952",
    open: null,
    requests: [],
    ...extra,
  };
}

async function routed(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

describe("what the form sends", () => {
  test("the amount as typed becomes a decimal string", () => {
    expect(amountOf("150000")).toBe("150000");
    expect(amountOf("150.000")).toBe("150000");
    expect(amountOf("$ 150.000,50")).toBe("150000.50");
    expect(amountOf("150,000")).toBe("150000");
    expect(amountOf("150000,5")).toBe("150000.5");
    for (const bad of ["", "0", "abc", "-5", "1.2.3"]) expect(amountOf(bad)).toBeNull();
  });

  test("the day is Bogotá's, not the browser's", () => {
    expect(bogotaDay(new Date("2026-11-10T03:30:00Z"))).toBe("2026-11-09");
    expect(bogotaDay(NOW)).toBe("2026-11-10");
    expect(bogotaDay(NOW, 30)).toBe("2026-10-11");
  });

  test("it asks for the amount, a recent day and the terms before sending anything", () => {
    const base: PayForm = { ...emptyForm(view(), NOW), acceptTerms: true };
    expect(base.amount).toBe("150000");
    expect(problems(base, NOW)).toEqual([]);
    expect(problems({ ...base, amount: "" }, NOW)).toEqual(["amount"]);
    expect(problems({ ...base, paidOn: "2026-11-11" }, NOW)).toEqual(["paidOn"]);
    expect(problems({ ...base, paidOn: "2026-09-01" }, NOW)).toEqual(["paidOn"]);
    expect(problems({ ...base, acceptTerms: false }, NOW)).toEqual(["terms"]);
    expect(toBody({ ...base, acceptTerms: false }, "v", NOW)).toBeNull();
  });

  test("the body carries the terms' version and trims what is optional away", () => {
    const form: PayForm = {
      ...emptyForm(view(), NOW),
      acceptTerms: true,
      reference: "  M 1234  ",
      payerName: "   ",
    };
    expect(toBody(form, "2026-11-10", NOW)).toEqual({
      amount: "150000",
      paid_on: "2026-11-10",
      method: "transfer",
      reference: "M 1234",
      payer_name: null,
      note: null,
      accept_terms: true,
      terms_version: "2026-11-10",
    });
  });

  test("with only the QR the method starts at Nequi", () => {
    const only = view({ pay: { holder: "T", breb_key: null, has_qr: true } });
    expect(emptyForm(only, NOW).method).toBe("nequi");
  });
});

describe("when the page speaks", () => {
  test("only a reader without cover or with it ending may ask", () => {
    for (const s of ["none", "expiring", "grace", "expired"]) expect(mayPay(s)).toBe(true);
    for (const s of ["trial", "active", "renewed", "suspended"]) expect(mayPay(s)).toBe(false);
  });

  test("closed: no holder, no key, no QR and no form - only a way to write", async () => {
    setLocale("es");
    const html = await routed(
      <PaymentRequestBody
        state="none"
        data={view({ available: false, locks: ["terms_draft"], pay: null })}
      />,
    );
    expect(html).toContain('data-testid="pay-closed"');
    expect(html).not.toContain("pay-form");
    expect(html).not.toContain("Titular de Prueba");
    expect(html).not.toContain("pay-qr");
    expect(html).toContain("wa.me/573016355952");
  });

  test("open: how to pay, then the form with the amount already filled", async () => {
    setLocale("es");
    const html = await routed(<PaymentRequestBody state="none" data={view()} />);
    expect(html).toContain('data-testid="pay-open"');
    expect(html).toContain("Titular de Prueba");
    expect(html).toContain("@predigol-prueba");
    expect(html).toContain('data-testid="pay-qr"');
    expect(html).toContain("/api/v1/me/payment-request/qr");
    expect(html).toContain("150.000 COP");
    expect(html).toContain('data-testid="pay-form"');
    expect(html).toContain('value="150000"');
  });

  test("a member with cover running sees nothing to pay", async () => {
    setLocale("es");
    const html = await routed(<PaymentRequestBody state="active" data={view()} />);
    expect(html).toBe("");
  });

  test("waiting: «pago en verificación», the day, what was declared and a way to cancel", async () => {
    setLocale("es");
    const html = await routed(
      <PaymentRequestBody state="none" data={view({ open: request(), requests: [request()] })} />,
    );
    expect(html).toContain('data-testid="pay-waiting"');
    expect(html).toContain("Pago en verificación");
    expect(html).toContain("un día hábil");
    expect(html).toContain("…4567");
    expect(html).toContain('data-testid="pay-cancel"');
    expect(html).not.toContain("pay-form");
    expect(html).not.toContain("pay-qr");
  });

  test("waiting is shown even if the cover is running (a renewal in verification)", async () => {
    setLocale("es");
    const html = await routed(
      <PaymentRequestBody state="active" data={view({ open: request(), requests: [request()] })} />,
    );
    expect(html).toContain('data-testid="pay-waiting"');
  });

  test("a refusal says why and lets the reader try again", async () => {
    setLocale("es");
    const refused = request({ status: "rejected", decision_code: "not_received" });
    const html = await routed(
      <PaymentRequestBody state="none" data={view({ requests: [refused] })} />,
    );
    expect(html).toContain('data-testid="pay-outcome"');
    expect(html).toContain('data-kind="rejected"');
    expect(html).toContain("todavía no vemos el dinero");
    expect(html).toContain('data-testid="pay-form"');
  });

  test("an annulled approval is told as such", () => {
    const annulled = request({ status: "approved", annulled: true });
    expect(lastOutcome([annulled])).toBe("annulled");
    expect(lastOutcome([request({ status: "approved" })])).toBeNull();
    expect(lastOutcome([])).toBeNull();
  });
});

describe("both languages", () => {
  test("every line exists in Spanish and English", () => {
    const keys = [
      "closedTitle",
      "closedBody",
      "howTitle",
      "amountToPay",
      "holder",
      "key",
      "copy",
      "copied",
      "qrAlt",
      "saveQr",
      "afterPaying",
      "formTitle",
      "fieldAmount",
      "fieldDate",
      "fieldMethod",
      "fieldReference",
      "referenceHelp",
      "fieldPayer",
      "fieldNote",
      "acceptTerms",
      "submit",
      "noCharge",
      "waitingTitle",
      "waitingBody",
      "waitingNoRepay",
      "cancel",
      "cancelConfirm",
      "cancelKeep",
      "annulled",
      "whatsapp",
      "whatsappText",
      "methods.nequi",
      "methods.transfer",
      "methods.other",
      "problem.amount",
      "problem.paidOn",
      "problem.terms",
      "reason.not_received",
      "reason.amount_mismatch",
      "reason.duplicate",
      "reason.unreadable",
      "reason.other",
    ];
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const key of keys)
        expect(
          t(`profile.membership.pay.${key}`, { date: "x", percent: 1, days: 1 }),
        ).not.toContain("profile.membership.pay");
    }
    setLocale("en");
    expect(t("profile.membership.pay.waitingTitle")).toBe("Payment being verified");
  });
});
