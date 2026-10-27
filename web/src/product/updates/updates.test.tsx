/// <reference types="bun" />
/**
 * Novedades (plan UX, B6; section 40), without a browser: every entry has an id the server accepts for «seen» (its date
 * and a slug), the newest first, its words in Spanish and English and a link only to a page that exists; «Más» marks it
 * while the newest entry is not the last one the reader saw; and an entry says it came from the readers only when it did.
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
import { UpdatesView } from "./UpdatesPage";
import { LATEST_UPDATE, UPDATES, UPDATE_ID, hasUnread, updateDay } from "./updates";

afterAll(() => setLocale("es"));

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/updates"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

describe("the entries", () => {
  test("each id is its day and a slug - the form the server keeps as seen - and none repeats", () => {
    expect(UPDATES.length).toBeGreaterThan(0);
    for (const e of UPDATES) {
      expect([e.id, UPDATE_ID.test(e.id)]).toEqual([e.id, true]);
      expect(e.id.length).toBeLessThanOrEqual(60); // the server's UpdatesSeenIn
      expect(Number.isNaN(Date.parse(updateDay(e.id)))).toBe(false);
    }
    expect(new Set(UPDATES.map((e) => e.id)).size).toBe(UPDATES.length);
    expect(new Set(UPDATES.map((e) => e.key)).size).toBe(UPDATES.length);
  });

  test("the newest first", () => {
    const days = UPDATES.map((e) => e.id.slice(0, 10));
    expect([...days].sort().reverse()).toEqual(days);
    expect(LATEST_UPDATE).toBe(UPDATES[0]!.id);
  });

  test("every entry has its words in Spanish and English, and a link only to a page that exists", () => {
    const pages = [
      /^\/my-picks$/,
      /^\/matches$/,
      /^\/picks$/,
      /^\/profile(#football)?$/,
      /^\/help$/,
    ];
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const e of UPDATES) {
        for (const part of ["title", "body"])
          expect(t(`support.updates.items.${e.key}.${part}`)).not.toContain("support.");
        if (e.to || e.go) {
          expect([e.id, pages.some((p) => p.test(e.to ?? ""))]).toEqual([e.id, true]);
          expect(t(`support.updates.go.${e.go}`)).not.toContain("support.");
        }
      }
      for (const key of [
        "title",
        "intro",
        "fromReaders",
        "suggest.title",
        "suggest.body",
        "suggest.action",
      ])
        expect(t(`support.updates.${key}`)).not.toContain("support.");
    }
  });
});

describe("the dot on «Más»", () => {
  test("while the newest entry is not the last one the reader saw", () => {
    expect(hasUnread(null, "2026-11-02-b")).toBe(true);
    expect(hasUnread(undefined, "2026-11-02-b")).toBe(true);
    expect(hasUnread("2026-10-27-a", "2026-11-02-b")).toBe(true);
    expect(hasUnread("2026-11-02-b", "2026-11-02-b")).toBe(false);
    expect(hasUnread(null, null)).toBe(false);
    expect(hasUnread(LATEST_UPDATE)).toBe(false);
  });
});

describe("the page", () => {
  test("every entry, newest first, with its day, its words and the way to see it; the way to suggest the next", async () => {
    setLocale("es");
    const out = await html(<UpdatesView entries={UPDATES} onSuggest={() => {}} />);
    const ids = [...out.matchAll(/data-update="([^"]+)"/g)].map((m) => m[1]);
    expect(ids).toEqual(UPDATES.map((e) => e.id));
    expect(out).toContain("Novedades");
    expect(out).toContain("27 oct 2026");
    expect(out).toContain(t("support.updates.items.myPicks.title"));
    expect(out).toContain('href="/my-picks"');
    expect(out).toContain('href="/profile#football"');
    expect(out).toContain('data-testid="updates-suggest-open"');
  });

  test("with messages to PrediGol off, the way to the help instead", async () => {
    setLocale("en");
    const out = await html(<UpdatesView entries={UPDATES} />);
    expect(out).toContain("What&#x27;s new");
    expect(out).not.toContain('data-testid="updates-suggest-open"');
    expect(out).toContain('href="/help"');
  });

  test("an entry says it came from the readers' comments only when it did", async () => {
    setLocale("es");
    const plain = await html(<UpdatesView entries={[{ id: "2026-11-02-x", key: "feedback" }]} />);
    expect(plain).not.toContain('data-testid="update-from-readers"');
    const theirs = await html(
      <UpdatesView entries={[{ id: "2026-11-02-x", key: "feedback", fromReaders: true }]} />,
    );
    expect(theirs).toContain('data-testid="update-from-readers"');
    expect(theirs).toContain(t("support.updates.fromReaders"));
    expect(renderToStaticMarkup(<p>{t("support.updates.intro")}</p>)).toContain("lo decimos");
  });
});
