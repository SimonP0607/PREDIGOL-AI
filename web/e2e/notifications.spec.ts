/**
 * The readers' notices on their devices (plan UX, B7; sections 34 and 35), in the browser against the API and the QA
 * messenger, with the browser's permission and push subscription simulated (a QA browser has no push service to reach)
 * and a stand-in push service on 127.0.0.1:9996 that the QA stack lists (FBI_PUSH_SERVICE_HOSTS, QA only):
 *
 * * Opening PrediGol never asks; the profile's «Notificaciones» shows this browser off; «Activar en este dispositivo»
 *   asks the browser once and the device is the account's (Chrome on Android for a Pixel 7); the categories switch and
 *   stay switched; the test notice crosses the real path - API, queue, messenger - and reaches the push service
 *   encrypted for this browser alone (RFC 8291: decrypted here with the browser's own key), with PrediGol's VAPID
 *   signature over the push service's origin; «Desactivar» stops it.
 * * The offer comes after a moment, never on opening: following a team brings PrediGol's own card with «Ahora no»;
 *   «Ahora no» keeps it away; on another device «Activar avisos» turns notices on from the card.
 * * The bell of a match that starts within 7 days: 15 minutes before, saved and kept, then removed; the star only
 *   follows.
 * * An iPhone in Safari is shown how to install PrediGol (notices reach the installed app only), never a button that
 *   cannot work; a browser that blocked notices is told how to allow them, and no offer comes to it.
 * * The owner's card in /admin/product: available, the devices and the week's notices - counts, never who.
 *
 * Every row is checked against SQL written here. Run with E2E_PUSH=1 against the QA stack with QA_PUSH=1 QA_MESSENGER=1
 * (a QA VAPID key and the stand-in's origin), one worker (the stand-in listens on one port), and E2E_DATABASE_URL; with
 * E2E_PUSH_OFF=1, against the QA stack without the key: nothing is offered anywhere - production's state until P12.
 */
import { execFileSync } from "node:child_process";
import { createDecipheriv, createECDH, hkdfSync, randomBytes, randomUUID } from "node:crypto";
import { createServer, type Server } from "node:http";
import {
  devices,
  expect,
  request,
  test,
  type APIRequestContext,
  type Browser,
  type BrowserContext,
  type Page,
} from "@playwright/test";
import { statePath } from "./accounts";
import { L, getJson, sendJson, skipWelcome, smallTargets } from "./support";

const BASE = process.env["E2E_BASE_URL"] ?? "http://127.0.0.1:5173";
const DB = (process.env["E2E_DATABASE_URL"] ?? "").replace(
  "postgresql+psycopg://",
  "postgresql://",
);
const OFF = process.env["E2E_PUSH_OFF"] === "1";
const PASSWORD = "Ring-the-bell-twice-26"; // gitleaks:allow - a QA account's password, made and deleted here
const PUSH_PORT = 9996;
const PUSH_ORIGIN = `http://127.0.0.1:${PUSH_PORT}`;
const PHONE = { width: 390, height: 844 };
const t = L.es;

test.describe.configure({ mode: "serial" });

function sql(query: string): string {
  return execFileSync("psql", [DB, "-v", "ON_ERROR_STOP=1", "-qAt", "-F", "|", "-c", query], {
    stdio: "pipe",
  })
    .toString()
    .trim();
}

// ── the stand-in push service ────────────────────────────────────────────────────────────────────────────────────

interface Delivery {
  path: string;
  headers: Record<string, string | string[] | undefined>;
  body: Buffer;
}

const received: Delivery[] = [];
let server: Server | null = null;

test.beforeAll(async () => {
  if (OFF) return;
  server = createServer((req, res) => {
    const chunks: Buffer[] = [];
    req.on("data", (c: Buffer) => chunks.push(c));
    req.on("end", () => {
      received.push({ path: req.url ?? "", headers: req.headers, body: Buffer.concat(chunks) });
      res.writeHead(201).end();
    });
  });
  await new Promise<void>((resolve) => server?.listen(PUSH_PORT, "127.0.0.1", resolve));
});

test.afterAll(async () => {
  await new Promise<void>((resolve) => (server ? server.close(() => resolve()) : resolve()));
});

/** A browser's push keys, as PushSubscription.toJSON() gives them, and the private half to read what arrives. */
function browserKeys() {
  const ecdh = createECDH("prime256v1");
  ecdh.generateKeys();
  const auth = randomBytes(16);
  return {
    ecdh,
    auth,
    endpoint: `${PUSH_ORIGIN}/push/${randomUUID()}`,
    p256dh: ecdh.getPublicKey().toString("base64url"),
    authText: auth.toString("base64url"),
  };
}

type Keys = ReturnType<typeof browserKeys>;

/** RFC 8291 (aes128gcm), the browser's side: what the messenger encrypted for this browser alone. */
function decrypt(body: Buffer, keys: Keys): unknown {
  const salt = body.subarray(0, 16);
  const idlen = body[20] ?? 0;
  const serverKey = body.subarray(21, 21 + idlen);
  const ciphertext = body.subarray(21 + idlen);
  const shared = keys.ecdh.computeSecret(serverKey);
  const info = Buffer.concat([Buffer.from("WebPush: info\0"), keys.ecdh.getPublicKey(), serverKey]);
  const ikm = Buffer.from(hkdfSync("sha256", shared, keys.auth, info, 32));
  const cek = Buffer.from(
    hkdfSync("sha256", ikm, salt, Buffer.from("Content-Encoding: aes128gcm\0"), 16),
  );
  const nonce = Buffer.from(
    hkdfSync("sha256", ikm, salt, Buffer.from("Content-Encoding: nonce\0"), 12),
  );
  const decipher = createDecipheriv("aes-128-gcm", cek, nonce);
  decipher.setAuthTag(ciphertext.subarray(ciphertext.length - 16));
  const plain = Buffer.concat([
    decipher.update(ciphertext.subarray(0, ciphertext.length - 16)),
    decipher.final(),
  ]);
  let end = plain.length - 1;
  while (end > 0 && plain[end] === 0) end -= 1;
  expect(plain[end], "the last record's delimiter").toBe(2);
  return JSON.parse(plain.subarray(0, end).toString("utf8"));
}

function claims(jwt: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(jwt.split(".")[1] ?? "", "base64url").toString("utf8")) as Record<
    string,
    unknown
  >;
}

// ── the browser, simulated where a QA browser cannot reach a push service ────────────────────────────────────────

/**
 * The Notification permission (``permission``, and ``answer`` to its question) and the service worker's push manager,
 * replaced before the app loads: the app subscribes with PrediGol's key and gets these keys and this endpoint.
 */
async function simulatePush(
  context: BrowserContext,
  keys: Keys,
  permission: NotificationPermission = "default",
  answer: NotificationPermission = "granted",
): Promise<void> {
  await context.addInitScript(
    ({ endpoint, p256dh, auth, permission: start, answer: reply }) => {
      let state = start;
      let current: unknown = null;
      const w = window as unknown as Record<string, unknown>;
      w["__pushAsked"] = 0;
      const subscription = (key: ArrayBuffer) => ({
        endpoint,
        options: { applicationServerKey: key, userVisibleOnly: true },
        toJSON: () => ({ endpoint, expirationTime: null, keys: { p256dh, auth } }),
        unsubscribe: () => {
          current = null;
          return Promise.resolve(true);
        },
      });
      const registration = {
        pushManager: {
          getSubscription: () => Promise.resolve(current),
          subscribe: (opts: { applicationServerKey: Uint8Array }) => {
            if (state !== "granted")
              return Promise.reject(new DOMException("no", "NotAllowedError"));
            current = subscription(new Uint8Array(opts.applicationServerKey).buffer);
            return Promise.resolve(current);
          },
        },
      };
      Object.defineProperty(window, "Notification", {
        configurable: true,
        value: {
          get permission() {
            return state;
          },
          requestPermission: () => {
            w["__pushAsked"] = (w["__pushAsked"] as number) + 1;
            if (state === "default") state = reply;
            return Promise.resolve(state);
          },
        },
      });
      Object.defineProperty(window, "PushManager", {
        configurable: true,
        value: function PushManager() {},
      });
      Object.defineProperty(navigator, "serviceWorker", {
        configurable: true,
        value: {
          getRegistration: () => Promise.resolve(registration),
          register: () => Promise.resolve(registration),
          ready: Promise.resolve(registration),
          controller: null,
          addEventListener: () => undefined,
        },
      });
    },
    { endpoint: keys.endpoint, p256dh: keys.p256dh, auth: keys.authText, permission, answer },
  );
}

// ── accounts ──────────────────────────────────────────────────────────────────────────────────────────────────────

interface Reader {
  id: number;
  email: string;
}

const made: Reader[] = [];

async function owner(): Promise<APIRequestContext> {
  return request.newContext({ baseURL: BASE, storageState: statePath("admin") });
}

async function account(tag: string): Promise<Reader> {
  const admin = await owner();
  const email = `e2e.push.${tag}.${Date.now()}@predigol.local`;
  const created = await sendJson<{ data: { id: number } }>(admin, "POST", "/api/v1/admin/users", {
    email,
    password: PASSWORD,
    role: "USER",
    language: "es",
    timezone: "America/Bogota",
    must_change_password: false,
  });
  await admin.dispose();
  expect(created.status, "the owner creates the test's account").toBe(201);
  const reader = { id: created.body.data.id, email };
  made.push(reader);
  return reader;
}

test.afterAll(async () => {
  const admin = await owner();
  for (const r of made) {
    const res = await sendJson(admin, "POST", `/api/v1/admin/users/${r.id}/anonymise`, {
      confirm: r.email,
    });
    expect([200, 409], `the test's account ${r.id} is deleted`).toContain(res.status);
  }
  await admin.dispose();
  if (!OFF && made.length) {
    const ids = made.map((r) => r.id).join(",");
    expect(
      sql(`SELECT count(*) FROM customer.push_subscriptions WHERE user_id IN (${ids})`),
      "an anonymised account keeps no device, bell or notice",
    ).toBe("0");
  }
});

async function device(
  browser: Browser,
  options: {
    phone?: string;
    keys?: Keys;
    permission?: NotificationPermission;
    answer?: NotificationPermission;
  } = {},
): Promise<{ context: BrowserContext; page: Page; keys: Keys }> {
  const keys = options.keys ?? browserKeys();
  const context = await browser.newContext({
    ...devices[options.phone ?? "Pixel 7"],
    viewport: PHONE,
    baseURL: BASE,
    locale: "es-ES",
    timezoneId: "America/Bogota",
  });
  await simulatePush(context, keys, options.permission, options.answer);
  return { context, page: await context.newPage(), keys };
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator('input[name="email"]').fill(email);
  await page.locator('input[name="password"]').fill(PASSWORD);
  await page.getByTestId("login-submit").click();
  await expect(page).not.toHaveURL(/\/login/);
  await skipWelcome(page.request);
  await page.goto("/home");
  const gate = page.getByTestId("consent-gate");
  await expect(gate.or(page.getByTestId("home-page"))).toBeVisible({ timeout: 30_000 });
  if (await gate.isVisible()) {
    for (const kind of ["terms", "privacy", "age_18", "risk_notice"])
      await gate.getByTestId(`consent-${kind}`).check();
    await gate.getByTestId("consent-submit").click();
    await expect(gate).toHaveCount(0);
  }
}

interface TodayBody {
  data: {
    matches: {
      data: Array<{
        fixture_id: number;
        status_group: string;
        kickoff_at: string;
        competition: { name: string };
        home: { id: number; name: string };
      }>;
    };
  };
}

/** A match later today (the QA seed puts one on the board, seed_a9.py) and its home team. */
async function laterToday(
  api: APIRequestContext,
): Promise<{ fixture: number; team: number; name: string }> {
  const today = await getJson<TodayBody>(api, "/api/v1/today");
  expect(today.status).toBe(200);
  const soon = today.body.data.matches.data.filter(
    (m) => m.status_group === "scheduled" && Date.parse(m.kickoff_at) > Date.now() + 30 * 60_000,
  );
  const match = soon.find((m) => m.competition.name === "QA Primera A") ?? soon[0];
  expect(match, "a match later today on the QA board").toBeTruthy();
  return {
    fixture: match?.fixture_id ?? 0,
    team: match?.home.id ?? 0,
    name: match?.home.name ?? "",
  };
}

interface PushState {
  available: boolean;
  public_key: string | null;
  devices: Array<{ id: number; family: string; system: string }>;
  categories: Record<string, boolean>;
}

async function waitForDelivery(endpoint: string, after: number): Promise<Delivery> {
  let found: Delivery | undefined;
  await expect(async () => {
    found = received.slice(after).find((d) => `${PUSH_ORIGIN}${d.path}` === endpoint);
    expect(found, "the QA messenger delivered the notice to the push service").toBeTruthy();
  }).toPass({ timeout: 60_000, intervals: [1_000] });
  return found as Delivery;
}

// ── the tests ─────────────────────────────────────────────────────────────────────────────────────────────────────

test("without PrediGol's key nothing is offered: no block in the profile, no bell, no card, no question in Ayuda", async ({
  browser,
}) => {
  test.skip(!OFF, "E2E_PUSH_OFF=1: the QA stack without the VAPID key");
  test.setTimeout(120_000);
  const reader = await account("off");
  const { context, page } = await device(browser);
  try {
    await signIn(page, reader.email);
    const state = await getJson<PushState>(page.request, "/api/v1/me/push");
    expect(state.body.available).toBe(false);
    await page.goto("/profile#notifications");
    await expect(page.getByTestId("notifications")).toBeVisible();
    await expect(page.getByTestId("push-section")).toHaveCount(0);
    const match = await laterToday(page.request);
    await page.goto(`/matches/${match.fixture}`);
    await expect(page.getByTestId("follow-star").first()).toBeVisible();
    await expect(page.getByTestId("match-bell")).toHaveCount(0);
    await page.locator(`[data-testid="follow-star"][data-team="${match.team}"]`).click();
    await page.waitForTimeout(2_000);
    await expect(page.getByTestId("push-offer")).toHaveCount(0);
    await page.goto("/help");
    await expect(page.getByTestId("help-page")).toBeVisible();
    await expect(page.getByText(t.support.faq.push.q)).toHaveCount(0);
    expect(
      await page.evaluate(() => (window as unknown as { __pushAsked: number }).__pushAsked),
    ).toBe(0);
  } finally {
    await context.close();
  }
});

test.describe("with PrediGol's key", () => {
  test.skip(OFF, "E2E_PUSH=1: the QA stack with QA_PUSH=1 QA_MESSENGER=1");

  let reader: Reader;

  test("from the profile: asked once, the device is the account's, the categories stay, the test notice arrives encrypted for this browser alone, and off again", async ({
    browser,
  }) => {
    test.setTimeout(240_000);
    reader = await account("profile");
    const { context, page, keys } = await device(browser);
    try {
      await signIn(page, reader.email);
      expect(
        await page.evaluate(() => (window as unknown as { __pushAsked: number }).__pushAsked),
        "opening PrediGol never asks",
      ).toBe(0);
      await page.goto("/profile#notifications");
      const section = page.getByTestId("push-section");
      await expect(section).toBeVisible();
      await expect(section.getByTestId("push-here")).toHaveAttribute("data-status", "off");
      await expect(section).toContainText(
        t.push.profile.help
          .replace("{from}", "22:00")
          .replace("{to}", "08:00")
          .replace("{cap}", "3"),
      );
      expect(await smallTargets(page, '[data-testid="push-section"]')).toEqual([]);
      await section.getByTestId("push-enable").click();
      await expect(section.getByTestId("push-here")).toHaveAttribute("data-status", "on");
      expect(
        await page.evaluate(() => (window as unknown as { __pushAsked: number }).__pushAsked),
      ).toBe(1);
      const [row] = sql(
        `SELECT id || '|' || family || '|' || system || '|' || endpoint || '|' || p256dh || '|' || auth FROM customer.push_subscriptions WHERE user_id = ${reader.id} AND revoked_at IS NULL`,
      ).split("\n");
      const [id, family, system, endpoint, p256dh, auth] = (row ?? "").split("|");
      expect([family, system, endpoint, p256dh, auth]).toEqual([
        "chrome",
        "android",
        keys.endpoint,
        keys.p256dh,
        keys.authText,
      ]);
      await expect(section.getByTestId("push-device")).toHaveCount(1);
      await expect(section.getByTestId("push-device")).toContainText("Chrome en Android");
      await expect(section.getByTestId("push-device")).toContainText(t.push.profile.here);

      // the categories: switched and kept
      const digest = section.getByTestId("push-category-digest").getByRole("switch");
      await expect(digest).toHaveAttribute("aria-checked", "true");
      await digest.click();
      await expect(digest).toHaveAttribute("aria-checked", "false");
      expect(sql(`SELECT push_off FROM customer.preferences WHERE user_id = ${reader.id}`)).toBe(
        "{digest}",
      );
      await page.reload();
      await expect(page.getByTestId("push-category-digest").getByRole("switch")).toHaveAttribute(
        "aria-checked",
        "false",
      );

      // the test notice: API → queue → QA messenger → the push service, encrypted for this browser
      const state = await getJson<PushState>(page.request, "/api/v1/me/push");
      const before = received.length;
      await page.getByTestId("push-test").click();
      await expect(page.getByText(t.push.profile.testSent)).toBeVisible();
      const delivery = await waitForDelivery(keys.endpoint, before);
      expect(delivery.headers["content-encoding"]).toBe("aes128gcm");
      expect(Number(delivery.headers["ttl"])).toBeGreaterThan(0);
      const authorization = String(delivery.headers["authorization"] ?? "");
      const [, jwt, k] = /^vapid t=([^,]+), k=(.+)$/.exec(authorization) ?? [];
      expect(k, "signed with PrediGol's key, the one the browser subscribed with").toBe(
        state.body.public_key,
      );
      expect(claims(jwt ?? "")["aud"]).toBe(PUSH_ORIGIN);
      const notice = decrypt(delivery.body, keys) as Record<string, string>;
      expect(notice["category"]).toBe("test");
      expect(notice["url"]).toBe("/profile#notifications");
      expect(notice["title"]?.length).toBeGreaterThan(0);
      // another browser's keys cannot read it
      expect(() => decrypt(delivery.body, browserKeys())).toThrow();
      expect(
        sql(
          `SELECT status || '|' || devices FROM customer.push_notices WHERE user_id = ${reader.id} AND category = 'test'`,
        ),
      ).toBe("sent|1");

      // off on this device, in one tap
      await page.getByTestId("push-disable").click();
      await expect(page.getByTestId("push-here")).toHaveAttribute("data-status", "off");
      expect(sql(`SELECT revoked_reason FROM customer.push_subscriptions WHERE id = ${id}`)).toBe(
        "unsubscribed",
      );
      await expect(page.getByTestId("push-no-devices")).toBeVisible();
    } finally {
      await context.close();
    }
  });

  test("the offer comes after following a team, never on opening; «Ahora no» keeps it away; on another device the card turns notices on", async ({
    browser,
  }) => {
    test.setTimeout(240_000);
    const fan = await account("offer");
    const first = await device(browser);
    try {
      await signIn(first.page, fan.email);
      const match = await laterToday(first.page.request);
      await first.page.goto(`/matches/${match.fixture}`);
      await expect(first.page.getByTestId("match-bell")).toBeVisible();
      await expect(first.page.getByTestId("push-offer")).toHaveCount(0);
      await first.page.locator(`[data-testid="follow-star"][data-team="${match.team}"]`).click();
      const card = first.page.getByTestId("push-offer");
      await expect(card).toBeVisible();
      await expect(card).toHaveAttribute("data-phase", "ask");
      await expect(card).toContainText(t.push.offer.follow.title.replace("{team}", match.name));
      await expect(card.getByTestId("push-offer-later")).toHaveText(t.push.offer.later);
      expect(await smallTargets(first.page, '[data-testid="push-offer"]')).toEqual([]);
      await card.getByTestId("push-offer-later").click();
      await expect(card).toHaveCount(0);
      expect(
        await first.page.evaluate(() => (window as unknown as { __pushAsked: number }).__pushAsked),
        "«Ahora no» never reaches the browser's question",
      ).toBe(0);
      // unfollow and follow again on another visit: «Ahora no» keeps it away from this device
      const star = first.page.locator(`[data-testid="follow-star"][data-team="${match.team}"]`);
      await star.click();
      await expect(star).toHaveAttribute("aria-pressed", "false");
      await first.page.evaluate(() => window.sessionStorage.clear());
      await first.page.reload();
      await star.click();
      await expect(star).toHaveAttribute("aria-pressed", "true");
      await first.page.waitForTimeout(2_000);
      await expect(first.page.getByTestId("push-offer")).toHaveCount(0);
    } finally {
      await first.context.close();
    }

    const second = await device(browser);
    try {
      await signIn(second.page, fan.email);
      const match = await laterToday(second.page.request);
      await second.page.goto(`/matches/${match.fixture}`);
      const star = second.page.locator(`[data-testid="follow-star"][data-team="${match.team}"]`);
      await star.click(); // following → not following
      await expect(star).toHaveAttribute("aria-pressed", "false");
      await star.click();
      const card = second.page.getByTestId("push-offer");
      await expect(card).toBeVisible();
      await card.getByTestId("push-offer-enable").click();
      await expect(card).toHaveAttribute("data-phase", "done");
      expect(
        sql(
          `SELECT count(*) FROM customer.push_subscriptions WHERE user_id = ${fan.id} AND revoked_at IS NULL AND endpoint = '${second.keys.endpoint}'`,
        ),
      ).toBe("1");
    } finally {
      await second.context.close();
    }
  });

  test("the bell of a match within 7 days: 15 minutes before, saved and kept, then removed - the star only follows", async ({
    browser,
  }) => {
    test.setTimeout(180_000);
    const fan = await account("bell");
    const { context, page } = await device(browser);
    try {
      await signIn(page, fan.email);
      const match = await laterToday(page.request);
      await page.goto(`/matches/${match.fixture}`);
      const bell = page.getByTestId("match-bell");
      await expect(bell).toHaveAttribute("aria-pressed", "false");
      await expect(bell).toHaveAttribute("aria-label", t.push.bell.add);
      await bell.click();
      const sheet = page.getByTestId("match-bell-sheet");
      await expect(sheet).toBeVisible();
      await expect(sheet).toContainText(t.push.bell.needsDevice);
      await expect(sheet).toContainText(t.push.bell.night);
      expect(await smallTargets(page, '[data-testid="match-bell-sheet"]')).toEqual([]);
      await sheet.getByTestId("match-bell-15").click();
      // no device yet: «Activar avisos y guardar» asks the browser from this tap, then saves
      await expect(sheet.getByTestId("match-bell-save")).toHaveText(t.push.bell.saveEnable);
      await sheet.getByTestId("match-bell-save").click();
      await expect(sheet).toHaveCount(0);
      await expect(bell).toHaveAttribute("aria-pressed", "true");
      expect(
        sql(
          `SELECT minutes_before FROM customer.match_alerts WHERE user_id = ${fan.id} AND fixture_id = ${match.fixture}`,
        ),
      ).toBe("15");
      expect(
        sql(
          `SELECT count(*) FROM customer.push_subscriptions WHERE user_id = ${fan.id} AND revoked_at IS NULL`,
        ),
      ).toBe("1");
      expect(
        sql(`SELECT count(*) FROM customer.favorites WHERE user_id = ${fan.id}`),
        "the bell follows no team",
      ).toBe("0");
      await page.reload();
      await expect(bell).toHaveAttribute("aria-pressed", "true");
      await bell.click();
      await expect(page.getByTestId("match-bell-15").locator("input")).toBeChecked();
      await page.getByTestId("match-bell-remove").click();
      await expect(bell).toHaveAttribute("aria-pressed", "false");
      expect(sql(`SELECT count(*) FROM customer.match_alerts WHERE user_id = ${fan.id}`)).toBe("0");
    } finally {
      await context.close();
    }
  });

  test("an iPhone in Safari is shown how to install PrediGol; a blocked browser how to allow notices - and no offer comes to either", async ({
    browser,
  }) => {
    test.setTimeout(180_000);
    const fan = await account("iphone");
    const iphone = await device(browser, { phone: "iPhone 13" });
    try {
      await signIn(iphone.page, fan.email);
      await iphone.page.goto("/profile#notifications");
      const here = iphone.page.getByTestId("push-here");
      await expect(here).toHaveAttribute("data-status", "needs_install");
      await expect(here.getByTestId("install-guide")).toContainText(t.push.install.iosStep2);
      await expect(iphone.page.getByTestId("push-enable")).toHaveCount(0);
      const match = await laterToday(iphone.page.request);
      await iphone.page.goto(`/matches/${match.fixture}`);
      await iphone.page.getByTestId("match-bell").click();
      const sheet = iphone.page.getByTestId("match-bell-sheet");
      await expect(sheet.getByTestId("install-guide")).toBeVisible();
      await expect(sheet.getByTestId("match-bell-save")).toBeDisabled();
    } finally {
      await iphone.context.close();
    }

    const blocked = await device(browser, { permission: "denied" });
    try {
      await signIn(blocked.page, fan.email);
      await blocked.page.goto("/profile#notifications");
      await expect(blocked.page.getByTestId("push-here")).toHaveAttribute("data-status", "denied");
      await expect(blocked.page.getByTestId("push-here-status")).toHaveText(
        t.push.profile.status.denied,
      );
      const match = await laterToday(blocked.page.request);
      await blocked.page.goto(`/matches/${match.fixture}`);
      await blocked.page.locator(`[data-testid="follow-star"][data-team="${match.team}"]`).click();
      await blocked.page.waitForTimeout(2_000);
      await expect(blocked.page.getByTestId("push-offer")).toHaveCount(0);
      expect(
        await blocked.page.evaluate(
          () => (window as unknown as { __pushAsked: number }).__pushAsked,
        ),
      ).toBe(0);
    } finally {
      await blocked.context.close();
    }
  });

  test("Ayuda answers the notices' questions, and the owner's card counts devices and notices, never who", async ({
    browser,
  }) => {
    test.setTimeout(120_000);
    const fan = await account("help");
    const { context, page } = await device(browser);
    try {
      await signIn(page, fan.email);
      await page.goto("/help");
      await expect(page.getByText(t.support.faq.push.q)).toBeVisible();
      await expect(page.getByText(t.support.faq.push_iphone.q)).toBeVisible();
    } finally {
      await context.close();
    }
    const admin = await browser.newContext({ storageState: statePath("admin"), baseURL: BASE });
    try {
      const page2 = await admin.newPage();
      await page2.goto("/admin/product");
      const card = page2.getByTestId("push-card");
      await expect(card.getByTestId("push-available")).toHaveText(L.en.admin.product.push.on);
      const text = (await card.textContent()) ?? "";
      expect(text).not.toMatch(/@predigol\.local|127\.0\.0\.1/);
      const sent = Number(
        sql(
          "SELECT count(*) FROM customer.push_notices WHERE status = 'sent' AND created_at > now() - interval '7 days'",
        ),
      );
      expect(sent, "the profile test's notice was sent").toBeGreaterThan(0);
      await expect(card.getByTestId("push-notices")).toBeVisible();
    } finally {
      await admin.close();
    }
  });
});
