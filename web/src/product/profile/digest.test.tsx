/// <reference types="bun" />
/**
 * Plan UX, B8 (section 33), without a browser: the weekly summary's switch in Notificaciones shows only while the API
 * offers the purpose (or to leave it), starts off, carries the processing policy's sentence and says since when; the
 * Privacy block lists an optional purpose only once the reader decided on it and sends its change to Notificaciones;
 * the console names the summary; every source of a decision and every error of the way out has its words. Asking for
 * it, leaving it from the profile and from the e-mail's link run in the browser (e2e/digest.spec.ts).
 */
import { afterAll, describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale, t } from "@/lib/i18n";
import { CATALOGS } from "@/lib/i18n/catalogs";
import type { ConsentPurpose, ConsentRecord, ConsentState } from "@/lib/api/v1/types_customer";
import { templateName } from "@/admin/messages";
import { DigestView } from "./DigestSection";
import { ConsentRow } from "./PrivacyPanel";
import { digestOf, shownPurposes } from "./consents";

afterAll(() => setLocale("es"));

const BACKEND = join(import.meta.dir, "..", "..", "..", "..", "backend");
const STATEMENT =
  "Quiero recibir por correo el resumen semanal de PrediGol: mis picks de la semana y cómo terminaron, los partidos de mis equipos y las novedades. Puedo darme de baja en un clic desde cualquier resumen o en mi perfil.";

function purpose(kind: ConsentPurpose["kind"], required: boolean): ConsentPurpose {
  return {
    kind,
    document: kind === "terms" || kind === "age_18" ? "terms" : "privacy",
    version: "2026-10-27-draft2",
    sha256: "a".repeat(64),
    statement: kind === "marketing_email" ? STATEMENT : `La frase de ${kind}`,
    required,
    withdrawable: kind === "privacy" || kind === "marketing_email",
    changes: null,
  };
}

function decision(kind: string, granted: boolean, at = "2026-10-27T15:00:00Z"): ConsentRecord {
  return {
    kind,
    granted,
    document: "privacy",
    version: "2026-10-27-draft2",
    sha256: "a".repeat(64),
    locale: "es",
    statement: STATEMENT,
    source: "profile",
    at,
  };
}

const REQUIRED = (["terms", "privacy", "age_18", "risk_notice"] as const).map((k) =>
  purpose(k, true),
);

function state(over: Partial<ConsentState> = {}): ConsentState {
  return { gate: true, due: [], purposes: REQUIRED, history: [], ...over };
}

function view(s: ConsentState): string {
  const digest = digestOf(s);
  if (!digest) return "";
  return renderToStaticMarkup(
    <DigestView digest={digest} busy={false} failure={null} onToggle={() => undefined} />,
  );
}

describe("the weekly summary in Notificaciones", () => {
  test("is not there while the API does not offer it", () => {
    expect(digestOf(undefined)).toBeNull();
    expect(digestOf(state())).toBeNull();
  });

  test("offered and never asked for: off, with the policy's sentence and how it arrives", () => {
    setLocale("es");
    const out = view(state({ purposes: [...REQUIRED, purpose("marketing_email", false)] }));
    expect(out).toContain('role="switch"');
    expect(out).toContain('aria-checked="false"');
    expect(out).toContain(STATEMENT);
    expect(out).toContain("Resumen semanal");
    expect(out).toContain("desde las 9:00 de tu zona horaria");
    expect(out).not.toContain('data-testid="digest-since"');
  });

  test("asked for: on, since when; left: off, since when", () => {
    setLocale("es");
    const offered = [...REQUIRED, purpose("marketing_email", false)];
    const on = view(state({ purposes: offered, history: [decision("marketing_email", true)] }));
    expect(on).toContain('aria-checked="true"');
    expect(on).toContain("Lo pediste el");
    const left = view(
      state({
        purposes: offered,
        history: [
          decision("marketing_email", false, "2026-10-28T10:00:00Z"),
          decision("marketing_email", true),
        ],
      }),
    );
    expect(left).toContain('aria-checked="false"');
    expect(left).toContain("Te diste de baja el");
    setLocale("en");
    expect(
      view(state({ purposes: offered, history: [decision("marketing_email", true)] })),
    ).toContain("You asked for it on");
  });
});

describe("the Privacy block", () => {
  test("lists the four the gate asks for always, and the optional one once the reader decided on it", () => {
    const offered = state({ purposes: [...REQUIRED, purpose("marketing_email", false)] });
    expect(shownPurposes(offered).map((p) => p.kind)).toEqual([
      "terms",
      "privacy",
      "age_18",
      "risk_notice",
    ]);
    const decided = { ...offered, history: [decision("marketing_email", false)] };
    expect(shownPurposes(decided).map((p) => p.kind)).toContain("marketing_email");
  });

  test("an optional purpose says it is optional and sends its change to Notificaciones, never the withdrawal of the authorisation", () => {
    setLocale("es");
    const out = renderToStaticMarkup(
      <ConsentRow
        purpose={purpose("marketing_email", false)}
        latest={decision("marketing_email", true)}
        busy={false}
        onDecide={async () => undefined}
      />,
    );
    expect(out).toContain('data-testid="privacy-optional"');
    expect(out).toContain('href="#notifications"');
    expect(out).toContain("Aceptado el");
    expect(out).not.toContain('data-testid="privacy-withdraw"');
    expect(out).not.toContain('data-testid="privacy-regrant"');
    const privacy = renderToStaticMarkup(
      <ConsentRow
        purpose={purpose("privacy", true)}
        latest={decision("privacy", true)}
        busy={false}
        onDecide={async () => undefined}
      />,
    );
    expect(privacy).toContain('data-testid="privacy-withdraw"');
    expect(privacy).not.toContain('data-testid="privacy-optional"');
  });

  test("every source a decision can have in the database has its words (migration 0105)", () => {
    const migration = readFileSync(
      join(BACKEND, "migrations", "versions", "0105_customer_marketing.py"),
      "utf8",
    );
    // SOURCES_BEFORE = ("gate", ...) and SOURCES = (*SOURCES_BEFORE, "email")
    const lines = [...migration.matchAll(/^SOURCES(?:_BEFORE)? = \(([^)]*)\)/gm)].map(
      (m) => m[1] ?? "",
    );
    const names = lines.flatMap((l) => [...l.matchAll(/"([a-z_]+)"/g)].map((m) => m[1] ?? ""));
    expect(names).toEqual(["gate", "profile", "activation", "email"]);
    for (const lang of ["es", "en"] as const) {
      const legal = CATALOGS[lang]["legal"] as { privacy: { source: Record<string, string> } };
      for (const name of names)
        expect([lang, name, Boolean(legal.privacy.source[name])]).toEqual([lang, name, true]);
    }
  });
});

describe("the console and the way out", () => {
  test("the console names the summary as commercial", () => {
    setLocale("es");
    expect(templateName("weekly_digest")).toContain("comercial");
    setLocale("en");
    expect(templateName("weekly_digest")).toContain("commercial");
  });

  test("the way out's refusals have their words", () => {
    for (const lang of ["es", "en"] as const) {
      setLocale(lang);
      for (const code of ["invalid_link", "not_offered", "too_many_attempts"])
        expect(t(`errors.code.${code}`)).not.toBe(`errors.code.${code}`);
      for (const key of [
        "unsubscribeTitle",
        "unsubscribeBody",
        "unsubscribeSubmit",
        "unsubscribeDone",
        "unsubscribeAlready",
        "unsubscribeInvalid",
        "unsubscribeProfile",
      ])
        expect(t(`auth.account.${key}`)).not.toBe(`auth.account.${key}`);
    }
  });
});
