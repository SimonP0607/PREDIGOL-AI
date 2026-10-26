/// <reference types="bun" />
/**
 * The product's navigation (plan UX, A15, section 36), without a browser: five destinations - Inicio, Partidos, Picks,
 * Mis picks and «Más» - on the phone's bar and the desk's alike; En vivo held by Partidos, whose board keeps its
 * address; «Más» with Parlays, Cuotas, Transparencia (once it is open to readers), Ayuda, Perfil and Glosario in the
 * plan's order, the install steps outside the installed app, and «Cerrar sesión»; labels of 12 px in both languages. The
 * browser half (whole at 320 px, 44 px, two taps to Perfil and Ayuda, WebKit) is e2e/responsive.spec.ts.
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
import { setLocale, t } from "@/lib/i18n";
import { BottomBar, TopNav } from "./Bars";
import { InstallSteps, MoreList } from "./MoreSheet";
import { currentMore, destinationOf, holds, moreItems, moreNav, userNav } from "./nav";

afterAll(() => setLocale("es"));

async function html(node: ReactNode, path = "/"): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: [path] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

/** The opening tag of the element with this test id. */
function tag(out: string, testId: string): string {
  return new RegExp(`<[a-z]+[^>]*data-testid="${testId}"[^>]*>`).exec(out)?.[0] ?? "";
}

describe("five destinations", () => {
  test("Inicio, Partidos, Picks and Mis picks are the bar's four addresses - En vivo, Parlays and Cuotas are not", () => {
    expect(userNav.map((i) => i.to)).toEqual(["/home", "/matches", "/picks", "/my-picks"]);
    expect(userNav.map((i) => i.to)).not.toContain("/live");
    expect(userNav.map((i) => i.to)).not.toContain("/parlays");
    expect(userNav.map((i) => i.to)).not.toContain("/odds");
  });

  test("each page lights one destination: the live board and a match are Partidos', a page of «Más» is «Más»'s", () => {
    const cases: Array<[string, string | null]> = [
      ["/home", "/home"],
      ["/matches", "/matches"],
      ["/matches/1414", "/matches"],
      ["/live", "/matches"],
      ["/picks", "/picks"],
      ["/my-picks", "/my-picks"],
      ["/parlays", "more"],
      ["/odds", "more"],
      ["/transparency", "more"],
      ["/help", "more"],
      ["/help/glossary", "more"],
      ["/help/messages/12", "more"],
      ["/profile", "more"],
      ["/legal/terms", null],
      ["/livestream", null],
    ];
    for (const [path, destination] of cases)
      expect([path, destinationOf(path)]).toEqual([path, destination]);
    const partidos = userNav[1]!;
    expect(holds(partidos, "/live")).toBe(true);
    expect(holds(partidos, "/live/extra")).toBe(true);
  });

  test("«Más» holds the plan's items in the plan's order; Transparencia only once the owner opened it", () => {
    expect(moreNav.map((i) => i.to)).toEqual([
      "/parlays",
      "/odds",
      "/transparency",
      "/help",
      "/profile",
      "/help/glossary",
    ]);
    expect(moreItems(false).map((i) => i.to)).not.toContain("/transparency");
    expect(moreItems(true).map((i) => i.to)).toContain("/transparency");
  });

  test("the row of «Más» a page belongs to is the longest address that holds it", () => {
    expect(currentMore("/help/glossary")?.to).toBe("/help/glossary");
    expect(currentMore("/help/messages/7")?.to).toBe("/help");
    expect(currentMore("/help")?.to).toBe("/help");
    expect(currentMore("/odds")?.to).toBe("/odds");
    expect(currentMore("/matches")).toBeNull();
  });

  test("every label and hint exists in Spanish and English", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const key of [
        ...userNav.map((i) => i.label),
        ...moreNav.flatMap((i) => [i.label, i.hint]),
        "nav.more",
        "nav.moreTitle",
        "nav.moreDescription",
        "nav.install.label",
        "nav.install.hint",
        "nav.install.ios",
        "nav.install.android",
        "nav.install.other",
        "nav.install.after",
      ]) {
        expect([locale, key, t(key)]).not.toEqual([locale, key, key]);
      }
    }
    setLocale("es");
    expect(t("nav.more")).toBe("Más");
    expect(t("nav.install.ios")).toContain("Agregar a Inicio");
  });
});

describe("the phone's bar", () => {
  test("five cells of 12 px - four links and the «Más» button - never 10 or 11 px", async () => {
    setLocale("es");
    const out = await html(<BottomBar pathname="/home" moreOpen={false} onMore={() => {}} />);
    expect(out.match(/data-testid="tab-label"/g)).toHaveLength(5);
    for (const id of ["tab-home", "tab-matches", "tab-picks", "tab-my-picks", "tab-more"]) {
      expect(tag(out, id)).toContain("text-xs");
      expect(tag(out, id)).not.toMatch(/text-\[0\.6/);
    }
    expect(out).toContain("grid-cols-5");
    expect(out).not.toContain("tab-live");
    expect(out).toContain(">Más<");
  });

  test("the cell of the page says so (aria-current); on the live board it is Partidos", async () => {
    const out = await html(<BottomBar pathname="/live" moreOpen={false} onMore={() => {}} />);
    expect(tag(out, "tab-matches")).toContain('aria-current="page"');
    expect(tag(out, "tab-home")).not.toContain("aria-current");
    expect(tag(out, "tab-more")).toContain('aria-expanded="false"');
    expect(tag(out, "tab-more")).toContain('aria-haspopup="dialog"');
  });

  test("on a page of «Más» its cell is lit; open, it says it is expanded", async () => {
    const out = await html(<BottomBar pathname="/odds" moreOpen onMore={() => {}} />);
    expect(tag(out, "tab-more")).toContain("text-gold");
    expect(tag(out, "tab-more")).toContain('aria-expanded="true"');
    expect(out.match(/aria-current="page"/g) ?? []).toHaveLength(0);
  });

  test("in English too, five labels", async () => {
    setLocale("en");
    const out = await html(<BottomBar pathname="/home" moreOpen={false} onMore={() => {}} />);
    for (const word of ["Home", "Matches", "Picks", "My picks", "More"])
      expect(out).toContain(`>${word}<`);
    setLocale("es");
  });
});

describe("the desk's top bar", () => {
  test("the same groups: four links and «Más»", async () => {
    setLocale("es");
    const out = await html(<TopNav pathname="/parlays" items={moreItems(true)} />);
    for (const id of ["nav-home", "nav-matches", "nav-picks", "nav-my-picks", "nav-more"]) {
      expect(tag(out, id)).not.toBe("");
    }
    expect(out).not.toContain("nav-live");
    expect(out).not.toContain('data-testid="nav-parlays"');
    // Parlays is a page of «Más»: the menu's trigger carries the mark
    expect(out).toMatch(/data-testid="nav-more"[\s\S]*bg-gold/);
  });
});

describe("«Más»", () => {
  const list = (pathname: string, standalone = false, transparency = true) =>
    html(
      <MoreList
        items={moreItems(transparency)}
        pathname={pathname}
        standalone={standalone}
        platform="android"
        onPick={() => {}}
        onSignOut={() => {}}
      />,
    );

  test("its rows in the plan's order, each 56 px tall, the page's own marked", async () => {
    setLocale("es");
    const out = await list("/help/glossary");
    const order = [
      "more-parlays",
      "more-odds",
      "more-transparency",
      "more-help",
      "more-profile",
      "more-glossary",
    ].map((id) => out.indexOf(`data-testid="${id}"`));
    expect(order.every((at) => at >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(tag(out, "more-glossary")).toContain('aria-current="page"');
    expect(tag(out, "more-help")).not.toContain("aria-current");
    expect(tag(out, "more-profile")).toContain("min-h-14");
    expect(tag(out, "more-sign-out")).toContain("min-h-12");
  });

  test("Transparencia waits for the owner; the install steps are not offered inside the installed app", async () => {
    const closed = await list("/home", false, false);
    expect(closed).not.toContain("more-transparency");
    expect(closed).toContain('data-testid="more-install"');
    const installed = await list("/home", true);
    expect(installed).not.toContain('data-testid="more-install"');
    expect(installed).toContain('data-testid="more-sign-out"');
  });

  test("«Instalar PrediGol» opens on this device's steps first, then the others and what changes once installed", async () => {
    setLocale("es");
    const out = await html(<InstallSteps platform="ios" defaultOpen />);
    const platforms = [...out.matchAll(/data-platform="(\w+)"/g)].map((m) => m[1]);
    expect(platforms).toEqual(["ios", "android", "other"]);
    expect(out).toContain("Agregar a Inicio");
    expect(out).toContain(t("nav.install.after").slice(0, 30));
    const closed = await html(<InstallSteps platform="android" />);
    expect(closed).not.toContain("data-platform");
    expect(tag(closed, "more-install-toggle")).toContain('aria-expanded="false"');
  });
});
