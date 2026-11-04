/// <reference types="bun" />
/**
 * Plan UX, B1 (section 21): the account centre's eight blocks - the line each says folded, in both languages, the
 * account's state in words, the addresses that lead to a block, the block that folds and the alias' rule. Opening and
 * closing by finger and keyboard, and every block's content, are checked in the browser (e2e/profile.spec.ts).
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { AccountSummary } from "@/lib/api/v1/types_account";
import type { MembershipSummary } from "@/lib/api/v1/types_membership";
import { Block } from "./Block";
import {
  ALIAS_MAX,
  BLOCKS,
  accountState,
  aliasProblem,
  blockOfHash,
  blockSummary,
  startsOpen,
} from "./centre";

function membership(over: Partial<MembershipSummary> = {}): MembershipSummary {
  return {
    state: "trial",
    ends_at: "2026-11-09T17:00:00Z",
    grace_until: "2026-11-12T17:00:00Z",
    kind: "trial",
    days_left: 14,
    limited: false,
    will_not_renew: false,
    ...over,
  };
}

function summary(over: Partial<AccountSummary> = {}): AccountSummary {
  return {
    account: {
      display_name: "Lectora",
      email: "lectora@example.org",
      created_at: "2026-10-26T15:00:00Z",
      admin: false,
    },
    region: { language: "es", timezone: "America/Bogota" },
    football: { leagues: 8, teams: 1, suggested: true },
    notifications: { email_on: 6, email_total: 6, email_status: "ok", sending: false },
    privacy: { consents_due: [], consents_at: null, open_requests: 0, next_deadline: null },
    security: {
      mfa_enabled: false,
      sessions: 1,
      last_sign_in_at: null,
      password_changed_at: null,
    },
    membership: membership(),
    help: { waiting: 0, answered: 0, whatsapp: false, support: true },
    ...over,
  };
}

const INTERNAL = /ROLE_|\bUSER\b|SUPER_ADMIN|SHADOW|QUALIFIED|shadow|qualified/;

describe("the account centre's folded lines", () => {
  test("eight blocks in the plan's order", () => {
    expect(BLOCKS).toEqual([
      "account",
      "football",
      "region",
      "notifications",
      "privacy",
      "security",
      "membership",
      "help",
    ]);
  });

  test("each block says its line in Spanish, never an internal word", () => {
    setLocale("es");
    const s = summary();
    const lines = Object.fromEntries(BLOCKS.map((k) => [k, blockSummary(k, s)]));
    expect(lines["account"]).toMatch(/^Lectora · En prueba hasta el /);
    expect(lines["football"]).toBe("Sugeridas para Colombia: 8 ligas");
    expect(lines["region"]).toMatch(/^Español · /);
    expect(lines["notifications"]).toBe("Correos: 6 de 6 temas");
    expect(lines["privacy"]).toBe("Autorizaciones al día · ninguna solicitud abierta");
    expect(lines["security"]).toBe("Sin verificación en dos pasos · 1 sesión abierta");
    expect(lines["membership"]).toMatch(/^En prueba hasta el /);
    expect(lines["help"]).toBe("Ningún mensaje abierto");
    for (const line of Object.values(lines)) expect(line).not.toMatch(INTERNAL);
  });

  test("the lines follow what the reader did", () => {
    setLocale("es");
    const s = summary({
      football: { leagues: 1, teams: 3, suggested: false },
      notifications: { email_on: 5, email_total: 6, email_status: "ok", sending: true },
      privacy: {
        consents_due: [],
        consents_at: "2026-10-26T15:00:00Z",
        open_requests: 2,
        next_deadline: "2026-11-10",
      },
      security: {
        mfa_enabled: true,
        sessions: 3,
        last_sign_in_at: null,
        password_changed_at: null,
      },
      help: { waiting: 1, answered: 0, whatsapp: true, support: true },
    });
    expect(blockSummary("football", s)).toBe("1 liga · 3 equipos");
    expect(blockSummary("notifications", s)).toBe("Correos: 5 de 6 temas");
    expect(blockSummary("privacy", s)).toMatch(/^2 solicitudes abiertas; la primera vence el /);
    expect(blockSummary("security", s)).toBe(
      "Verificación en dos pasos activada · 3 sesiones abiertas",
    );
    expect(blockSummary("help", s)).toBe("1 mensaje espera respuesta");
    expect(
      blockSummary("help", { ...s, help: { ...s.help, waiting: 1, answered: 2 } }),
      "an answer to read comes first",
    ).toBe("2 mensajes respondidos");
    expect(
      blockSummary("privacy", { ...s, privacy: { ...s.privacy, consents_due: ["terms"] } }),
      "an owed consent comes first",
    ).toBe("Tienes 1 autorización por aceptar");
    expect(
      blockSummary("notifications", {
        ...s,
        notifications: { ...s.notifications, email_status: "bounced" },
      }),
    ).toBe("Tu correo rebotó: ahora no te llega nada");
    expect(
      blockSummary("football", { ...s, football: { leagues: 0, teams: 0, suggested: false } }),
    ).toBe("Aún no sigues ligas ni equipos");
  });

  test("in English too", () => {
    setLocale("en");
    const s = summary();
    expect(blockSummary("football", s)).toBe("Suggested for Colombia: 8 leagues");
    expect(blockSummary("security", s)).toBe("No two-step verification · 1 open session");
    expect(blockSummary("region", s)).toMatch(/^English|^Español/);
    setLocale("es");
  });
});

describe("the account's state in words", () => {
  test("«Activa», «En prueba hasta el …», «Administrador» - never a role's code", () => {
    setLocale("es");
    expect(accountState(true, null)).toBe("Administrador");
    expect(accountState(false, null)).toBe("Activa");
    expect(accountState(false, membership({ state: "none", ends_at: null }))).toBe("Activa");
    expect(accountState(false, membership())).toMatch(/^En prueba hasta el /);
    expect(accountState(false, membership({ state: "active", kind: "paid" }))).toMatch(
      /^Activa hasta el /,
    );
    expect(accountState(false, membership({ state: "expiring", kind: "trial" }))).toMatch(
      /^Tu prueba termina el /,
    );
    expect(accountState(false, membership({ state: "expiring", kind: "paid" }))).toMatch(
      /^Vence el /,
    );
    expect(accountState(false, membership({ state: "grace", kind: "paid" }))).toMatch(
      /^En gracia hasta el /,
    );
    expect(accountState(false, membership({ state: "expired" }))).toBe("Vencida");
    expect(accountState(false, membership({ state: "suspended" }))).toBe("Suspendida");
  });
});

describe("the addresses that lead to a block", () => {
  test("a block's name, and the old addresses of what it holds", () => {
    expect(blockOfHash("#privacy")).toBe("privacy");
    expect(blockOfHash("#football")).toBe("football");
    expect(blockOfHash("#membership")).toBe("membership");
    expect(blockOfHash("notifications")).toBe("notifications");
    expect(blockOfHash("#language")).toBe("region");
    expect(blockOfHash("#timezone")).toBe("region");
    expect(blockOfHash("#sessions")).toBe("security");
    expect(blockOfHash("")).toBeNull();
    expect(blockOfHash("#nothing")).toBeNull();
  });
});

describe("a block that folds", () => {
  const render = (open: boolean, line: string | null = "Una línea") =>
    renderToStaticMarkup(
      <Block
        id="privacy"
        icon={null}
        title="Privacidad y datos"
        summary={line}
        open={open}
        onToggle={() => undefined}
      >
        <p data-testid="inside">dentro</p>
      </Block>,
    );

  test("folded: its line under the title, the header a button that says it is closed, nothing inside mounted", () => {
    const html = render(false);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("Una línea");
    expect(html).not.toContain("dentro");
    expect(html).toMatch(/role="region"[^>]*hidden=""/);
    expect(html).toContain('data-open="false"');
    expect(html).toContain('id="privacy"');
  });

  test("open: the content, no line (the content says it), the header says it is open", () => {
    const html = render(true);
    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain("dentro");
    expect(html).not.toContain("Una línea");
    expect(html).not.toMatch(/role="region"[^>]*hidden=""/);
  });

  test("open at a desk, folded under 1024 px, folded without a screen to ask", () => {
    const at = (desk: boolean) => ({ matchMedia: () => ({ matches: desk }) as MediaQueryList });
    expect(startsOpen(at(true))).toBe(true);
    expect(startsOpen(at(false))).toBe(false);
    expect(startsOpen(undefined)).toBe(false);
    expect(
      startsOpen({
        matchMedia: () => {
          throw new Error("no screen");
        },
      }),
    ).toBe(false);
  });
});

describe("the alias", () => {
  test("never empty, never longer than 80 characters", () => {
    expect(aliasProblem("Lectora")).toBeNull();
    expect(aliasProblem("   ")).toBe("empty");
    expect(aliasProblem("")).toBe("empty");
    expect(aliasProblem("x".repeat(ALIAS_MAX))).toBeNull();
    expect(aliasProblem("x".repeat(ALIAS_MAX + 1))).toBe("long");
    expect(aliasProblem(`  ${"x".repeat(ALIAS_MAX)}  `), "spaces around do not count").toBeNull();
  });
});
