/// <reference types="bun" />
/**
 * Plan UX, A7: the pages that get a reader in without the owner, and the console's words about a deleted account.
 * The pages themselves - invitation, activation, recovery and unlocking with the e-mail's link - run in the browser
 * against the API (e2e/account.spec.ts): they need the session's provider.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { setLocale } from "@/lib/i18n";
import { AnonymiseAccount } from "@/admin/AnonymiseAccount";
import { anonymisedSummary, isAnonymised } from "@/admin/anonymised";
import type { AdminAnonymised } from "@/lib/api/v1/types_auth";
import { isAccountPath } from "./accountPaths";

function withQueries(node: React.ReactNode): string {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>{node}</QueryClientProvider>,
  );
}

describe("the account pages", () => {
  test("are the seven public addresses, with or without a trailing slash", () => {
    for (const path of [
      "/activate",
      "/forgot-password",
      "/reset-password/",
      "/unlock",
      "/unsubscribe/",
      "/register",
      "/verify-email/",
    ]) {
      expect(isAccountPath(path), path).toBe(true);
    }
    for (const path of [
      "/",
      "/login",
      "/activate/x",
      "/unlocked",
      "/profile",
      "/unsubscribe/x",
      "/registered",
      "/verify",
    ]) {
      expect(isAccountPath(path), path).toBe(false);
    }
  });
});

describe("deleting an account in the console", () => {
  const result: AdminAnonymised = {
    user: {} as AdminAnonymised["user"],
    picks: 3,
    parlays: 1,
    sessions: 2,
    messages_dropped: 0,
    trail_rows: 5,
  };

  test("says what went in counts, never in content", () => {
    setLocale("es");
    const es = anonymisedSummary(result);
    for (const n of ["3 picks", "1 combinadas", "2 sesiones", "0 correos", "5 filas"]) {
      expect(es).toContain(n);
    }
    setLocale("en");
    expect(anonymisedSummary(result)).toContain("5 rows of the trail masked");
    setLocale("es");
  });

  test("knows an anonymised account by the address it keeps", () => {
    expect(isAnonymised("deleted-41@deleted.invalid")).toBe(true);
    expect(isAnonymised("ana@example.org")).toBe(false);
  });

  test("withdraws an invitation or deletes, and asks in a dialog that is closed until then", () => {
    setLocale("es");
    const invited = withQueries(<AnonymiseAccount userId={7} email="ana@example.org" invited />);
    expect(invited).toContain("Retirar invitación");
    expect(invited).not.toContain('data-testid="anonymise-dialog-7"');
    const active = withQueries(<AnonymiseAccount userId={8} email="bea@example.org" />);
    expect(active).toContain("Borrar (anonimizar)");
    expect(active).toContain('data-testid="anonymise-8"');
  });
});
