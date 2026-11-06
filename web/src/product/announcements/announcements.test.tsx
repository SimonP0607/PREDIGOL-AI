/// <reference types="bun" />
import { afterAll, beforeEach, describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { I18nProvider, setLocale } from "@/lib/i18n";
import { UpdatesView } from "@/product/updates/UpdatesPage";
import {
  CRITICAL_KINDS,
  KINDS,
  emptyForm,
  localInput,
  phraseOk,
  problem,
  toBody,
  withKind,
  type Form,
} from "@/admin/announcements";
import type { PublicNotice } from "@/lib/api/v1/types_announcements";
import { DISMISSED_KEY, readClosed, rememberClosed, visibleNotices } from "./banner";

const NOW = Date.parse("2026-11-05T12:00:00Z");
const notice = (over: Partial<PublicNotice>): PublicNotice => ({
  id: 1,
  kind: "general",
  title_es: "Aviso",
  title_en: "Notice",
  body_es: "Cuerpo del aviso",
  body_en: "Notice body",
  starts_at: "2026-11-05T10:00:00Z",
  ends_at: "2026-11-05T18:00:00Z",
  critical: false,
  ...over,
});

const store = new Map<string, string>();
const g = globalThis as unknown as { window?: unknown };
const realWindow = g.window;
g.window = {
  localStorage: {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  },
};
afterAll(() => {
  g.window = realWindow;
  setLocale("es");
});

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/updates"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

describe("the owner's banners", () => {
  beforeEach(() => store.clear());

  test("they show in the reader's language, the most urgent kind first", () => {
    const shown = visibleNotices(
      [notice({ id: 1, kind: "general" }), notice({ id: 2, kind: "incident" })],
      [],
      "en",
      NOW,
    );
    expect(shown.map((n) => n.id)).toEqual([2, 1]);
    expect(shown[0]?.title).toBe("Notice");
    expect(visibleNotices([notice({})], [], "es", NOW)[0]?.title).toBe("Aviso");
  });

  test("only between their dates, even from a stale cache", () => {
    const early = notice({ id: 3, starts_at: "2026-11-05T13:00:00Z" });
    const late = notice({ id: 4, ends_at: "2026-11-05T11:00:00Z" });
    expect(visibleNotices([early, late], [], "es", NOW)).toEqual([]);
  });

  test("a closed one stays closed on this browser; the next shows", () => {
    const closed = rememberClosed(1);
    expect(readClosed()).toEqual([1]);
    expect(visibleNotices([notice({ id: 1 }), notice({ id: 2 })], closed, "es", NOW)).toHaveLength(
      1,
    );
  });

  test("without usable storage it still works", () => {
    store.set(DISMISSED_KEY, "{not json");
    expect(readClosed()).toEqual([]);
  });
});

describe("the communiqué form", () => {
  const ok = (): Form => ({
    ...emptyForm(new Date("2026-11-05T12:00:00")),
    title_es: "Mantenimiento",
    title_en: "Maintenance",
    body_es: "Una pausa corta.",
    body_en: "A short pause.",
  });

  test("there is no promotion", () => {
    expect(KINDS).toEqual(["maintenance", "incident", "update", "general"]);
    expect(CRITICAL_KINDS).toEqual(["maintenance", "incident"]);
  });

  test("a well-formed one passes and becomes the API's body", () => {
    const form = ok();
    expect(problem(form)).toBeNull();
    const body = toBody(form);
    expect(body.kind).toBe("general");
    expect(Date.parse(body.ends_at)).toBeGreaterThan(Date.parse(body.starts_at));
  });

  test("it says which rule is broken", () => {
    expect(problem({ ...ok(), title_es: "ab" })).toBe("texts");
    expect(problem({ ...ok(), body_en: "<b>x</b> hola" })).toBe("texts");
    expect(problem({ ...ok(), ends: ok().starts })).toBe("dates");
    expect(problem({ ...ok(), to_banner: false })).toBe("destination");
    expect(problem({ ...ok(), to_updates: true })).toBe("updates");
    expect(problem({ ...ok(), critical: true })).toBe("critical");
    expect(problem({ ...ok(), kind: "incident", to_email: true })).toBe("email");
    expect(problem({ ...ok(), kind: "incident", critical: true, to_email: true })).toBeNull();
    expect(
      problem({
        ...ok(),
        kind: "incident",
        critical: true,
        to_email: true,
        body_es: "x".repeat(201),
      }),
    ).toBe("email");
  });

  test("changing the kind drops what the new kind cannot carry", () => {
    const incident = { ...ok(), kind: "incident" as const, critical: true, to_email: true };
    const general = withKind(incident, "general");
    expect(general.critical).toBe(false);
    expect(general.to_email).toBe(false);
    const update = withKind({ ...ok(), kind: "update", to_updates: true }, "general");
    expect(update.to_updates).toBe(false);
  });

  test("only the exact word publishes", () => {
    expect(phraseOk("PUBLICAR")).toBe(true);
    expect(phraseOk(" PUBLICAR ")).toBe(true);
    expect(phraseOk("publicar")).toBe(false);
    expect(phraseOk("PUBLICA")).toBe(false);
  });

  test("the local input is the owner's clock", () => {
    expect(localInput(new Date(2026, 10, 5, 7, 5))).toBe("2026-11-05T07:05");
  });
});

describe("Novedades with the owner's updates", () => {
  test("his entry leads the list in the reader's language", async () => {
    const owner = [
      {
        id: 7,
        title_es: "Seguir equipos",
        title_en: "Follow teams",
        body_es: "Ahora puedes seguir equipos.",
        body_en: "You can now follow teams.",
        starts_at: "2026-11-05T09:00:00Z",
      },
    ];
    setLocale("es");
    const es = await html(<UpdatesView entries={[]} owner={owner} />);
    expect(es).toContain('data-update="owner-7"');
    expect(es).toContain("Seguir equipos");
    setLocale("en");
    const en = await html(
      <I18nProvider locale="en">
        <UpdatesView entries={[]} owner={owner} />
      </I18nProvider>,
    );
    expect(en).toContain("Follow teams");
    expect(en).not.toContain("Seguir equipos");
  });
});
