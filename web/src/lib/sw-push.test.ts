/// <reference types="bun" />
/**
 * The notices in the real public/sw.js (plan UX, B7; section 34), against a stand-in for the worker's global scope: every
 * push shows a notification - with what the messenger sent, or PrediGol's own words when the message cannot be read
 * (Safari withdraws the permission from a push that shows nothing) -, the same tag replaces the older one, and a tap
 * opens its page of PrediGol marked with its category: an open window of PrediGol goes there and comes to the front,
 * otherwise a new one opens; another site's address, a page written as //host or /\host, opens Inicio.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const ORIGIN = "https://predigol.example";

type Listener = (event: unknown) => void;

interface Shown {
  title: string;
  options: { body: string; tag: string; icon: string; badge: string; data: { url: string } };
}

interface FakeWindow {
  url: string;
  navigated: string[];
  focused: number;
  controlled: boolean;
}

function loadWorker(windows: FakeWindow[] = []) {
  const listeners: Record<string, Listener> = {};
  const shown: Shown[] = [];
  const opened: string[] = [];
  const self = {
    location: new URL(ORIGIN),
    addEventListener: (type: string, fn: Listener) => {
      listeners[type] = fn;
    },
    skipWaiting: () => undefined,
    registration: {
      showNotification: (title: string, options: Shown["options"]) => {
        shown.push({ title, options });
        return Promise.resolve();
      },
    },
    clients: {
      claim: () => Promise.resolve(),
      matchAll: () =>
        Promise.resolve(
          windows.map((w) => ({
            url: w.url,
            focus: () => {
              w.focused += 1;
              return Promise.resolve(w);
            },
            navigate: (url: string) => {
              if (!w.controlled) return Promise.reject(new TypeError("not controlled"));
              w.navigated.push(url);
              return Promise.resolve({
                focus: () => {
                  w.focused += 1;
                  return Promise.resolve(w);
                },
              });
            },
          })),
        ),
      openWindow: (url: string) => {
        opened.push(url);
        return Promise.resolve(null);
      },
    },
  };
  const source = readFileSync(join(import.meta.dir, "..", "..", "public", "sw.js"), "utf8");
  const caches = { open: () => Promise.resolve({ addAll: () => Promise.resolve() }) };
  new Function("self", "caches", "fetch", source)(self, caches, () => undefined);
  return { listeners, shown, opened };
}

async function push(worker: ReturnType<typeof loadWorker>, data: unknown, raw = false) {
  let pending: Promise<unknown> = Promise.resolve();
  worker.listeners["push"]?.({
    data:
      data === undefined
        ? null
        : {
            json: () => {
              if (raw) throw new SyntaxError("not JSON");
              return data;
            },
          },
    waitUntil: (p: Promise<unknown>) => (pending = p),
  });
  await pending;
  return worker.shown.at(-1);
}

async function tap(worker: ReturnType<typeof loadWorker>, data: unknown) {
  let closed = 0;
  let pending: Promise<unknown> = Promise.resolve();
  worker.listeners["notificationclick"]?.({
    notification: {
      data,
      close: () => {
        closed += 1;
      },
    },
    waitUntil: (p: Promise<unknown>) => (pending = p),
  });
  await pending;
  return closed;
}

const NOTICE = {
  title: "Ganado: tu pick de Atlético Nacional–Millonarios",
  body: "Mira cómo se liquidó.",
  url: "/matches/42#postmatch",
  tag: "result:pick:7",
  category: "result",
};

describe("a push shows a notification, always", () => {
  test("with the messenger's words, its tag and the page it opens marked with its category", async () => {
    const shown = await push(loadWorker(), NOTICE);
    expect(shown?.title).toBe(NOTICE.title);
    expect(shown?.options.body).toBe(NOTICE.body);
    expect(shown?.options.tag).toBe("result:pick:7");
    expect(shown?.options.icon).toMatch(/^\/brand\/.+\.png$/);
    expect(shown?.options.data.url).toBe("/matches/42?notice=result#postmatch");
  });

  test("a message that cannot be read, an empty one or one without a title: PrediGol's own words, Inicio", async () => {
    for (const [data, raw] of [
      [{}, true],
      [undefined, false],
      [{ title: "   " }, false],
      ["just a string", false],
    ] as const) {
      const shown = await push(loadWorker(), data, raw);
      expect(shown?.title).toBe("PrediGol");
      expect(shown?.options.data.url.startsWith("/home")).toBe(true);
    }
  });

  test("a title and a line longer than the queue allows are cut, never refused", async () => {
    const shown = await push(loadWorker(), {
      ...NOTICE,
      title: "t".repeat(500),
      body: "b".repeat(900),
    });
    expect(shown?.title.length).toBe(120);
    expect(shown?.options.body.length).toBe(300);
  });

  test.each([
    ["https://evil.example/x", "/home?notice=result"],
    ["//evil.example/x", "/home?notice=result"],
    ["/\\evil.example/x", "/home?notice=result"],
    ["javascript:alert(1)", "/home?notice=result"],
    ["/my-picks", "/my-picks?notice=result"],
    ["/profile#notifications", "/profile?notice=result#notifications"],
  ])("only PrediGol's own pages: %s opens %s", async (url, expected) => {
    const shown = await push(loadWorker(), { ...NOTICE, url });
    expect(shown?.options.data.url).toBe(expected);
  });

  test("a category that is not a word is not written into the address", async () => {
    const shown = await push(loadWorker(), { ...NOTICE, category: "x&y=1" });
    expect(shown?.options.data.url).toBe("/matches/42#postmatch");
  });
});

describe("a tap opens the notice's page", () => {
  const url = "/matches/42?notice=result#postmatch";

  test("an open window of PrediGol goes to the page and comes to the front", async () => {
    const w: FakeWindow = { url: `${ORIGIN}/home`, navigated: [], focused: 0, controlled: true };
    const worker = loadWorker([w]);
    expect(await tap(worker, { url })).toBe(1);
    expect(w.navigated).toEqual([url]);
    expect(w.focused).toBe(1);
    expect(worker.opened).toEqual([]);
  });

  test("no window, another site's window or one this worker cannot move: a new window", async () => {
    const other: FakeWindow = {
      url: "https://elsewhere.example/",
      navigated: [],
      focused: 0,
      controlled: true,
    };
    const stuck: FakeWindow = {
      url: `${ORIGIN}/home`,
      navigated: [],
      focused: 0,
      controlled: false,
    };
    for (const windows of [[], [other], [stuck]]) {
      const worker = loadWorker(windows);
      await tap(worker, { url });
      expect(worker.opened).toEqual([url]);
    }
    expect(other.navigated).toEqual([]);
  });

  test("whatever a notification carries, a tap never leaves PrediGol", async () => {
    for (const data of [
      { url: "//evil.example" },
      { url: "https://evil.example" },
      null,
      { url: 7 },
    ]) {
      const worker = loadWorker();
      await tap(worker, data);
      expect(worker.opened).toEqual(["/home"]);
    }
  });
});
