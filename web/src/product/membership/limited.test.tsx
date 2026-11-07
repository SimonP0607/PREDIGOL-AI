/// <reference types="bun" />
/**
 * What a limited account sees instead of a page (plan UX, A8): an ended membership, a suspended account, and - since a
 * registered account has no trial - one that was never given a period.
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
import type { MembershipSummary } from "@/lib/api/v1/types_membership";
import { setLocale } from "@/lib/i18n";
import { LimitedAccess } from "./LimitedAccess";

afterAll(() => setLocale("es"));

async function routed(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function summary(state: MembershipSummary["state"]): MembershipSummary {
  return {
    state,
    kind: null,
    limited: true,
    enforced: true,
    ends_at: null,
    grace_until: null,
    days_left: null,
    will_not_renew: false,
  } as unknown as MembershipSummary;
}

describe("the limited screen says why", () => {
  test.each([
    ["none", "Tu cuenta está creada", "Todavía no tiene el acceso a PrediGol activado"],
    ["expired", "Tu membresía terminó", "Al renovar vuelve todo"],
    ["suspended", "Tu cuenta está suspendida", "Escríbenos"],
  ] as const)("%s", async (state, title, body) => {
    setLocale("es");
    const html = await routed(<LimitedAccess membership={summary(state)} />);
    expect(html).toContain(`data-state="${state}"`);
    expect(html).toContain(title);
    expect(html).toContain(body);
  });

  test("an account without a period promises no renewal and still opens its data", async () => {
    setLocale("es");
    const html = await routed(<LimitedAccess membership={summary("none")} />);
    expect(html).not.toContain("renov");
    for (const id of ["limited-profile", "limited-my-picks", "limited-export", "limited-help"]) {
      expect(html).toContain(id);
    }
  });

  test("in English", async () => {
    setLocale("en");
    const html = await routed(<LimitedAccess membership={summary("none")} />);
    expect(html).toContain("Your account is created");
  });
});
