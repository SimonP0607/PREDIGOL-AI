/// <reference types="bun" />
/**
 * The product's navigation (plan UX, A15, section 36), without a browser: five destinations - Inicio, Partidos, Picks,
 * Mis picks and «Más» - on the phone's bar and the desk's alike; En vivo held by Partidos, whose board keeps its
 * address; «Más» with Parlays, Cuotas, Transparencia (once it is open to readers), Ayuda, Perfil, Glosario and Novedades
 * (with its dot while unread, B6) in the plan's order, the install steps outside the installed app, and «Cerrar sesión»;
 * labels of 12 px in both languages. The
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
import {
  adminDestinations,
  adminGroupOf,
  adminHome,
  adminNav,
  currentMore,
  destinationOf,
  holds,
  moreItems,
  moreNav,
  UPDATES_PATH,
  userNav,
  readFoldedAdminGroups,
  writeFoldedAdminGroups,
} from "./nav";

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
      "/news",
      "/help",
      "/profile",
      "/help/glossary",
      "/updates",
    ]);
    expect(UPDATES_PATH).toBe("/updates");
    expect(moreItems(false).map((i) => i.to)).not.toContain("/transparency");
    expect(moreItems(true).map((i) => i.to)).toContain("/transparency");
    // Noticias (decision 2) only while its section is open (FBI_NEWS_FEED)
    expect(moreItems(true).map((i) => i.to)).not.toContain("/news");
    expect(moreItems(true, true).map((i) => i.to)).toContain("/news");
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
        "nav.unread",
        "nav.moreUnread",
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
    // lit: the label in the page's white and the pill behind its icon (never the colour alone: aria-expanded says it)
    expect(tag(out, "tab-more")).toContain("data-active");
    expect(tag(out, "tab-more")).toContain("text-foreground");
    expect(out).toMatch(/data-testid="tab-more"[\s\S]*?bg-primary-soft/);
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
  test("the same groups: four links and «Más»; from 1280 px Parlays, Cuotas and Noticias are pills too (sheet S5)", async () => {
    setLocale("es");
    const out = await html(<TopNav pathname="/parlays" items={moreItems(true, true)} />);
    for (const id of ["nav-home", "nav-matches", "nav-picks", "nav-my-picks", "nav-more"]) {
      expect(tag(out, id)).not.toBe("");
    }
    expect(out).not.toContain("nav-live");
    // the wide desk's pills: there, hidden under 1280 px, the one the reader is on marked
    for (const id of ["nav-parlays", "nav-odds", "nav-news"]) {
      expect(tag(out, id)).toContain("hidden xl:inline-flex");
    }
    expect(tag(out, "nav-parlays")).toContain('aria-current="page"');
    expect(tag(out, "nav-odds")).not.toContain("aria-current");
    // under 1280 px Parlays is a page of «Más»: the trigger carries the mark, and gives it up where the pill shows
    expect(tag(out, "nav-more")).toContain("data-active");
    expect(tag(out, "nav-more")).toContain("bg-primary-soft");
    expect(tag(out, "nav-more")).toContain("xl:bg-transparent");
  });

  test("without the Noticias section there is no pill for it, and «Más» keeps its mark on its own pages", async () => {
    setLocale("es");
    const out = await html(<TopNav pathname="/help" items={moreItems(true)} />);
    expect(out).not.toContain('data-testid="nav-news"');
    expect(tag(out, "nav-more")).toContain("bg-primary-soft");
    expect(tag(out, "nav-more")).not.toContain("xl:bg-transparent");
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

  test("the language has a row of its own, before «Cerrar sesión», once it left the top bar - and none without it", async () => {
    setLocale("es");
    const out = await html(
      <MoreList
        items={moreItems(true)}
        pathname="/home"
        standalone={false}
        platform="android"
        onPick={() => {}}
        onSignOut={() => {}}
        language={<button type="button">ES</button>}
      />,
    );
    const row = out.indexOf('data-testid="more-language"');
    expect(row).toBeGreaterThan(out.indexOf('data-testid="more-updates"'));
    expect(row).toBeLessThan(out.indexOf('data-testid="more-sign-out"'));
    expect(out.slice(row, row + 600)).toContain("Idioma");
    expect(tag(out, "more-language")).toContain("min-h-14");
    expect(await list("/home")).not.toContain("more-language");
  });

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
      "more-updates",
    ].map((id) => out.indexOf(`data-testid="${id}"`));
    expect(order.every((at) => at >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
    expect(tag(out, "more-glossary")).toContain('aria-current="page"');
    expect(tag(out, "more-help")).not.toContain("aria-current");
    expect(tag(out, "more-profile")).toContain("min-h-14");
    expect(tag(out, "more-sign-out")).toContain("min-h-12");
  });

  test("«Escríbenos por WhatsApp» is a row of «Más» only once the owner gave the number - and there is no floating bubble", async () => {
    setLocale("es");
    const without = await list("/home");
    expect(without).not.toContain('data-testid="more-whatsapp"');
    const withNumber = await html(
      <MoreList
        items={moreItems(true)}
        pathname="/home"
        standalone={false}
        platform="android"
        onPick={() => {}}
        onSignOut={() => {}}
        whatsapp="573001234567"
      />,
    );
    const row = tag(withNumber, "more-whatsapp");
    expect(row).toContain("https://wa.me/573001234567?text=");
    expect(row).toContain("min-h-14");
    expect(withNumber).toContain("Escríbenos por WhatsApp");
    expect(withNumber).not.toContain("fixed");
  });

  test("Novedades carries a dot while it holds an entry the reader has not seen - with its words for a screen reader", async () => {
    setLocale("es");
    const seen = await list("/home");
    expect(seen).not.toContain('data-testid="unread-dot"');
    const unread = await html(
      <MoreList
        items={moreItems(true)}
        pathname="/home"
        standalone={false}
        platform="android"
        onPick={() => {}}
        onSignOut={() => {}}
        unread={[UPDATES_PATH]}
      />,
    );
    const row = /<a[^>]*data-testid="more-updates"[\s\S]*?<\/a>/.exec(unread)?.[0] ?? "";
    expect(row).toContain('data-testid="unread-dot"');
    expect(row).toContain("sin leer");
    expect([...unread.matchAll(/data-testid="unread-dot"/g)]).toHaveLength(1);
    const bar = await html(
      <BottomBar pathname="/home" moreOpen={false} onMore={() => {}} moreUnread />,
    );
    expect(bar).toContain('data-testid="tab-more-dot"');
    expect(bar).toContain("hay novedades");
    const quiet = await html(<BottomBar pathname="/home" moreOpen={false} onMore={() => {}} />);
    expect(quiet).not.toContain('data-testid="tab-more-dot"');
    const top = await html(
      <TopNav pathname="/home" items={moreItems(true)} unread={[UPDATES_PATH]} />,
    );
    expect(tag(top, "nav-more")).toBeTruthy();
    expect(top).toMatch(/data-testid="nav-more"[\s\S]*?data-testid="unread-dot"/);
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

describe("the console's menu in five groups (plan maestro UX/UI 2026, decision 12)", () => {
  // the 28 destinations the menu had before the regrouping, less «Clientes», which is a view of «Usuarios» since AP-A03 (its
  // old address redirects): none else may be lost, none added
  const BEFORE = [
    "overview",
    "picks",
    "performance",
    "odds",
    "support",
    "models",
    "backtesting",
    "analytics",
    "operation",
    "learning",
    "competitions",
    "teams",
    "players",
    "referees",
    "rankings",
    "data-truth",
    "data-quality",
    "system",
    "storage",
    "migration",
    "users",
    "messages",
    "announcements",
    "payments",
    "product",
    "audit",
    "settings",
  ].map((slug) => `/admin/${slug}`);

  test("the same destinations less «Clientes» (27), each exactly once, «Resumen» first", () => {
    const now = adminDestinations.map((item) => item.to);
    expect(now).toHaveLength(27);
    expect(new Set(now).size).toBe(27);
    expect([...now].sort()).toEqual([...BEFORE].sort());
    expect(now[0]).toBe("/admin/overview");
    expect(adminHome.to).toBe("/admin/overview");
  });

  test("five groups: 6, 3, 5, 5 and 7", () => {
    expect(adminNav.map((g) => [g.key, g.items.length])).toEqual([
      ["customers", 6],
      ["market", 3],
      ["intelligence", 5],
      ["football", 5],
      ["system", 7],
    ]);
  });

  test("a path finds its group; «Resumen» and a page outside the menu belong to none", () => {
    expect(adminGroupOf("/admin/payments")).toBe("customers");
    expect(adminGroupOf("/admin/odds")).toBe("market");
    expect(adminGroupOf("/admin/operation")).toBe("intelligence");
    expect(adminGroupOf("/admin/teams")).toBe("football");
    expect(adminGroupOf("/admin/audit")).toBe("system");
    expect(adminGroupOf("/admin/overview")).toBeNull();
    expect(adminGroupOf("/admin/ai-layer")).toBeNull();
  });

  test("what the browser folded is remembered, and nothing it stores can break the menu", () => {
    const kept = new Map<string, string>();
    const store = {
      getItem: (k: string) => kept.get(k) ?? null,
      setItem: (k: string, v: string) => void kept.set(k, v),
    };
    expect([...readFoldedAdminGroups(store)]).toEqual([]);
    writeFoldedAdminGroups(store, new Set(["football", "intelligence"]));
    expect([...readFoldedAdminGroups(store)].sort()).toEqual(["football", "intelligence"]);
    for (const junk of ["{", '"football"', '["nope", 7, "system"]', "null"]) {
      kept.set([...kept.keys()][0] ?? "k", junk);
      const read = [...readFoldedAdminGroups(store)];
      expect(read.every((k) => k === "system")).toBe(true);
    }
    expect([...readFoldedAdminGroups(null)]).toEqual([]);
    const refuses = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    };
    expect([...readFoldedAdminGroups(refuses)]).toEqual([]);
    expect(() => writeFoldedAdminGroups(refuses, new Set(["system"]))).not.toThrow();
  });
});

describe("the unified plan's bars (FBI_NAV_V2; decisions D-01 and D-02)", () => {
  const v2 = { v2: true, news: true, profiles: false };

  test("the phone's bar: Inicio, Partidos, Noticias, Picks and «Más»; without Noticias open, the bar of always", async () => {
    const { barNav } = await import("./nav");
    expect(barNav(v2).map((i) => i.to)).toEqual(["/home", "/matches", "/news", "/picks"]);
    expect(barNav({ ...v2, news: false }).map((i) => i.to)).toEqual(userNav.map((i) => i.to));
    expect(barNav().map((i) => i.to)).toEqual(userNav.map((i) => i.to));
    const out = await html(
      <BottomBar pathname="/news" moreOpen={false} onMore={() => {}} flags={v2} />,
    );
    expect(out).toContain('data-testid="tab-news"');
    expect(out).not.toContain('data-testid="tab-my-picks"');
  });

  test("«Mis picks» moves to «Más», Noticias leaves it, Equipos joins it with the profiles", async () => {
    const { moreItems, destinationOf } = await import("./nav");
    const rows = moreItems(true, true, v2).map((i) => i.to);
    expect(rows[0]).toBe("/my-picks");
    expect(rows).not.toContain("/news");
    expect(rows).not.toContain("/teams");
    expect(moreItems(true, true, { ...v2, profiles: true }).map((i) => i.to)).toContain("/teams");
    expect(destinationOf("/my-picks", v2)).toBe("more");
    expect(destinationOf("/news", v2)).toBe("/news");
  });

  test("the desk: Mis picks and Parlays from 1280 px, Cuotas only from 1600 px, Equipos from 1024 px with the profiles", async () => {
    const { deskExtras, moreHide } = await import("./nav");
    const extras = deskExtras({ ...v2, profiles: true }).map((x) => `${x.item.to}@${x.from}`);
    expect(extras).toEqual(["/teams@lg", "/my-picks@xl", "/parlays@xl", "/odds@wide"]);
    expect(moreHide("/odds", v2)).toBe("min-[1600px]:hidden");
    expect(moreHide("/help", v2)).toBeUndefined();
    const out = await html(<TopNav pathname="/home" items={moreItems(true, true)} flags={v2} />);
    expect(tag(out, "nav-odds")).toContain("min-[1600px]:inline-flex");
    expect(tag(out, "nav-my-picks")).toContain("xl:inline-flex");
  });

  test("the private section is the owner's alone, and only with the switch", async () => {
    const { privateItems } = await import("./nav");
    expect(privateItems(false, v2)).toEqual([]);
    expect(privateItems(true, { ...v2, v2: false })).toEqual([]);
    expect(privateItems(true, v2).map((i) => i.to)).toEqual(["/admin/intelligence"]);
  });
});
