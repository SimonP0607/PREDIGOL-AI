/// <reference types="bun" />
/**
 * Web Push in the browser (plan UX, B7; section 34), with a stand-in for the browser: an iPhone in Safari is told to
 * install PrediGol, a browser without a service worker or the Push API cannot; the browser's own question comes first
 * and from the reader's tap; the subscription uses PrediGol's key (and is made again after a new key); the server gets
 * the endpoint, the keys, the family and the system - never anything else; stopping tells the server and the browser;
 * this browser is «on» only while it is one of the account's live devices; a notice's opening is counted by its
 * category, and its mark leaves the address.
 */
import { describe, expect, test } from "bun:test";
import type { PushSubscribeIn, PushUnsubscribeIn } from "@/lib/api/v1/types_push";
import {
  browserFamily,
  browserSystem,
  deviceState,
  disableOnThisDevice,
  enableOnThisDevice,
  eventCategory,
  keyBytes,
  pushSupport,
  rememberedDevice,
  sameKey,
  withoutNoticeMark,
  type PushHost,
} from "./push";

const UA = {
  iphone:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1",
  iphoneApp:
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
  ipadDesktop:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
  android:
    "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
  samsung:
    "Mozilla/5.0 (Linux; Android 14; SM-S911B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/25.0 Chrome/121.0.0.0 Mobile Safari/537.36",
  windowsEdge:
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
  macFirefox: "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.4; rv:131.0) Gecko/20100101 Firefox/131.0",
  macSafari:
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
  linuxChrome:
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
};

/** A public key as GET /me/push gives it: a P-256 point, 65 bytes, base64url (RFC 8291's example, public). */
const PUBLIC_POINT =
  "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"; // gitleaks:allow - a public point
/** Another public point: the same curve point negated (y replaced by p - y), so another key. */
const OTHER_POINT = negated(PUBLIC_POINT);
function negated(point: string): string {
  const bytes = keyBytes(point);
  const p = BigInt("0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff");
  let y = 0n;
  for (const b of bytes.slice(33)) y = (y << 8n) | BigInt(b);
  let ny = p - y;
  const out = new Uint8Array(65);
  out.set(bytes.slice(0, 33));
  for (let i = 64; i >= 33; i -= 1) {
    out[i] = Number(ny & 0xffn);
    ny >>= 8n;
  }
  return btoa(String.fromCharCode(...out))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

const ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc:APA91b";
const P256DH = "B" + "x".repeat(86);
const AUTH = "y".repeat(22);

interface Fake {
  host: PushHost;
  calls: string[];
  store: Map<string, string>;
  subscription: { current: FakeSub | null };
}

interface FakeSub {
  endpoint: string;
  options: { applicationServerKey: ArrayBuffer | null };
  toJSON: () => { endpoint: string; keys: Record<string, string> };
  unsubscribe: () => Promise<boolean>;
}

function sub(calls: string[], endpoint = ENDPOINT, key = PUBLIC_POINT): FakeSub {
  return {
    endpoint,
    options: { applicationServerKey: keyBytes(key).buffer },
    toJSON: () => ({ endpoint, keys: { p256dh: P256DH, auth: AUTH } }),
    unsubscribe: () => {
      calls.push(`browser.unsubscribe:${endpoint}`);
      return Promise.resolve(true);
    },
  };
}

function fake({
  ua = UA.android,
  permission = "default" as NotificationPermission,
  answer = "granted" as NotificationPermission,
  worker = true,
  push = true,
  standalone = false,
  existing = null as FakeSub | null,
  registered = true,
} = {}): Fake {
  const calls: string[] = [];
  const store = new Map<string, string>();
  const subscription = { current: existing };
  const notification = {
    permission,
    requestPermission: () => {
      calls.push("requestPermission");
      notification.permission = answer;
      return Promise.resolve(answer);
    },
  };
  const registration = {
    pushManager: {
      getSubscription: () => Promise.resolve(subscription.current),
      subscribe: (options: { userVisibleOnly: boolean; applicationServerKey: Uint8Array }) => {
        calls.push(
          `subscribe:${options.userVisibleOnly}:${sameKey(options.applicationServerKey.buffer as ArrayBuffer, keyBytes(PUBLIC_POINT))}`,
        );
        subscription.current = sub(calls, `${ENDPOINT}-new`);
        return Promise.resolve(subscription.current);
      },
    },
  };
  const host: PushHost = {
    navigator: {
      userAgent: ua,
      maxTouchPoints: ua === UA.ipadDesktop ? 5 : 0,
      standalone,
      ...(worker
        ? {
            serviceWorker: {
              getRegistration: () => Promise.resolve(registered ? registration : undefined),
            },
          }
        : {}),
    },
    matchMedia: () => ({ matches: false }),
    Notification: notification,
    ...(push ? { PushManager: function PushManager() {} } : {}),
    localStorage: {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
      removeItem: (k: string) => void store.delete(k),
    },
  };
  return { host, calls, store, subscription };
}

function api(calls: string[], id = 41, fail = false) {
  const bodies: Array<PushSubscribeIn | PushUnsubscribeIn> = [];
  return {
    bodies,
    subscribe: (body: PushSubscribeIn) => {
      calls.push("api.subscribe");
      bodies.push(body);
      return fail ? Promise.reject(new Error("422 unknown_push_service")) : Promise.resolve({ id });
    },
    unsubscribe: (body: PushUnsubscribeIn) => {
      calls.push("api.unsubscribe");
      bodies.push(body);
      return Promise.resolve();
    },
  };
}

describe("whether this device can receive notices", () => {
  test("an iPhone or iPad in Safari must install PrediGol first; installed, it can (iOS 16.4+)", () => {
    expect(pushSupport(fake({ ua: UA.iphone, push: false }).host)).toBe("needs_install");
    expect(pushSupport(fake({ ua: UA.ipadDesktop, push: false }).host)).toBe("needs_install");
    expect(pushSupport(fake({ ua: UA.iphoneApp, standalone: true }).host)).toBe("supported");
    // an older iPhone, installed but without the Push API
    expect(pushSupport(fake({ ua: UA.iphoneApp, standalone: true, push: false }).host)).toBe(
      "unsupported",
    );
  });

  test("a browser without a service worker or the Push API cannot", () => {
    expect(pushSupport(fake({}).host)).toBe("supported");
    expect(pushSupport(fake({ worker: false }).host)).toBe("unsupported");
    expect(pushSupport(fake({ push: false }).host)).toBe("unsupported");
    expect(pushSupport(undefined)).toBe("unsupported");
  });

  test.each([
    [UA.android, "chrome", "android"],
    [UA.samsung, "other", "android"],
    [UA.windowsEdge, "edge", "windows"],
    [UA.macFirefox, "firefox", "macos"],
    [UA.macSafari, "safari", "macos"],
    [UA.linuxChrome, "chrome", "linux"],
    [UA.iphone, "safari", "ios"],
    [UA.iphoneApp, "safari", "ios"],
  ])("%#: its family and system as words of a closed list", (ua, family, system) => {
    expect(browserFamily(ua)).toBe(family as never);
    expect(browserSystem(ua)).toBe(system as never);
  });

  test("an iPad asking for the desktop site is an iPad", () => {
    expect(browserSystem(UA.ipadDesktop, 5)).toBe("ios");
    expect(browserSystem(UA.ipadDesktop, 0)).toBe("macos");
  });

  test("PrediGol's key in bytes: 65, a P-256 point; a subscription made with another key is another key's", () => {
    const bytes = keyBytes(PUBLIC_POINT);
    expect(bytes.length).toBe(65);
    expect(bytes[0]).toBe(4);
    expect(sameKey(bytes.buffer, keyBytes(PUBLIC_POINT))).toBe(true);
    expect(sameKey(keyBytes(OTHER_POINT).buffer, bytes)).toBe(false);
    expect(sameKey(null, bytes)).toBe(false);
  });
});

describe("turning notices on, from the reader's tap", () => {
  test("the browser's question comes first, then the subscription with PrediGol's key, then the server", async () => {
    const f = fake({});
    const a = api(f.calls);
    const result = await enableOnThisDevice(PUBLIC_POINT, a, f.host);
    expect(result).toEqual({ ok: true, deviceId: 41 });
    expect(f.calls).toEqual(["requestPermission", "subscribe:true:true", "api.subscribe"]);
    expect(a.bodies[0]).toEqual({
      endpoint: `${ENDPOINT}-new`,
      keys: { p256dh: P256DH, auth: AUTH },
      family: "chrome",
      system: "android",
      installed: false,
    });
    expect(rememberedDevice(f.host)).toEqual({ id: 41, endpoint: `${ENDPOINT}-new` });
  });

  test("the question is asked synchronously inside the tap: nothing awaits before it", () => {
    const f = fake({});
    void enableOnThisDevice(PUBLIC_POINT, api(f.calls), f.host);
    expect(f.calls).toEqual(["requestPermission"]);
  });

  test("a «no» stops there; a question closed without an answer too; nothing reaches the server", async () => {
    for (const [answer, reason] of [
      ["denied", "denied"],
      ["default", "dismissed"],
    ] as const) {
      const f = fake({ answer });
      const a = api(f.calls);
      expect(await enableOnThisDevice(PUBLIC_POINT, a, f.host)).toEqual({ ok: false, reason });
      expect(f.calls).toEqual(["requestPermission"]);
      expect(a.bodies).toEqual([]);
    }
    const blocked = fake({ permission: "denied" });
    expect(await enableOnThisDevice(PUBLIC_POINT, api(blocked.calls), blocked.host)).toEqual({
      ok: false,
      reason: "denied",
    });
    expect(blocked.calls).toEqual([]);
  });

  test("already allowed: no question; the browser's own subscription is kept while it has PrediGol's key", async () => {
    const f = fake({ permission: "granted" });
    f.subscription.current = sub(f.calls);
    const a = api(f.calls);
    expect((await enableOnThisDevice(PUBLIC_POINT, a, f.host)).ok).toBe(true);
    expect(f.calls).toEqual(["api.subscribe"]);
    expect((a.bodies[0] as PushSubscribeIn).endpoint).toBe(ENDPOINT);
  });

  test("a subscription made with another key (the owner changed PrediGol's) is made again", async () => {
    const f = fake({ permission: "granted" });
    f.subscription.current = sub(f.calls, ENDPOINT, OTHER_POINT);
    const a = api(f.calls);
    expect((await enableOnThisDevice(PUBLIC_POINT, a, f.host)).ok).toBe(true);
    expect(f.calls).toEqual([
      `browser.unsubscribe:${ENDPOINT}`,
      "subscribe:true:true",
      "api.subscribe",
    ]);
  });

  test("an iPhone in Safari, a browser without a worker: nothing is asked", async () => {
    for (const f of [fake({ ua: UA.iphone, push: false }), fake({ registered: false })]) {
      const result = await enableOnThisDevice(PUBLIC_POINT, api(f.calls), f.host);
      expect(result.ok).toBe(false);
      expect(f.calls.filter((c) => c !== "requestPermission")).toEqual([]);
    }
  });

  test("the server refusing the address: failed, and this browser is not remembered", async () => {
    const f = fake({ permission: "granted" });
    const result = await enableOnThisDevice(PUBLIC_POINT, api(f.calls, 41, true), f.host);
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toBe("failed");
    expect(rememberedDevice(f.host)).toBeNull();
  });
});

describe("this browser, afterwards", () => {
  test("«on» only while it is one of the account's live devices, with the permission and the subscription", async () => {
    const f = fake({ permission: "granted" });
    await enableOnThisDevice(PUBLIC_POINT, api(f.calls), f.host);
    expect(await deviceState([41, 7], f.host)).toEqual({ status: "on", deviceId: 41, moved: null });
    // removed from another device: this browser no longer receives
    expect((await deviceState([7], f.host)).status).toBe("off");
  });

  test("blocked, cannot, an iPhone in Safari, not yet", async () => {
    expect((await deviceState([], fake({ permission: "denied" }).host)).status).toBe("denied");
    expect((await deviceState([], fake({ worker: false }).host)).status).toBe("unsupported");
    expect((await deviceState([], fake({ registered: false }).host)).status).toBe("unsupported");
    expect((await deviceState([], fake({ ua: UA.iphone, push: false }).host)).status).toBe(
      "needs_install",
    );
    expect((await deviceState([], fake({}).host)).status).toBe("off");
  });

  test("the push service gave the browser a new address: the server is told again", async () => {
    const f = fake({ permission: "granted" });
    await enableOnThisDevice(PUBLIC_POINT, api(f.calls), f.host);
    f.subscription.current = sub(f.calls, `${ENDPOINT}-moved`);
    const state = await deviceState([41], f.host);
    expect(state.status).toBe("on");
    expect(state.moved?.endpoint).toBe(`${ENDPOINT}-moved`);
  });

  test("turning it off tells the server (by the address, in the body) and the browser, and forgets it", async () => {
    const f = fake({ permission: "granted" });
    await enableOnThisDevice(PUBLIC_POINT, api(f.calls), f.host);
    f.calls.length = 0;
    const a = api(f.calls);
    await disableOnThisDevice(a, f.host);
    expect(f.calls).toEqual(["api.unsubscribe", `browser.unsubscribe:${ENDPOINT}-new`]);
    expect(a.bodies).toEqual([{ endpoint: `${ENDPOINT}-new` }]);
    expect(rememberedDevice(f.host)).toBeNull();
  });

  test("without a subscription left, the remembered device is stopped by its id", async () => {
    const f = fake({ permission: "granted" });
    await enableOnThisDevice(PUBLIC_POINT, api(f.calls), f.host);
    f.subscription.current = null;
    const a = api(f.calls);
    await disableOnThisDevice(a, f.host);
    expect(a.bodies).toEqual([{ device_id: 41 }]);
  });
});

describe("a notice opened", () => {
  test("its category is counted by the product's events; the reader's own test is not", () => {
    for (const c of ["result", "lineup", "digest", "reminder", "account"]) {
      expect(eventCategory(c)).toBe(c as never);
    }
    expect(eventCategory("test")).toBeNull();
    expect(eventCategory("promo")).toBeNull();
    expect(eventCategory(null)).toBeNull();
  });

  test("the mark leaves the address and everything else stays", () => {
    expect(withoutNoticeMark("?notice=result")).toBe("");
    expect(withoutNoticeMark("?s=noticias&notice=lineup")).toBe("?s=noticias");
    expect(withoutNoticeMark("")).toBe("");
  });
});
