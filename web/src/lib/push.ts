/**
 * Web Push in the browser (plan UX, B7; section 34): whether this device can receive PrediGol's notices, asking for
 * the permission only from the reader's own tap, subscribing with PrediGol's key, and remembering which of the
 * account's devices this browser is.
 *
 * - An iPhone or iPad receives notices only in the installed app (iOS 16.4 or later): in Safari's tab the answer is
 *   «needs_install», and the page shows how to install it instead of a button that cannot work.
 * - The browser's own question comes first in `enableOnThisDevice`, called from the tap on «Activar avisos» (PrediGol's own
 *   card, with «Ahora no», always comes before it): Safari answers it only inside the reader's gesture.
 * - The service worker is registered in production builds only (lib/pwa.ts): without one, this browser cannot receive
 *   notices and says so.
 * - Which device of the account this browser is lives in the browser (`predigol.push.device`: the id the server gave it
 *   and the push service's address). The address leaves the browser only in the body of the requests that subscribe or
 *   stop it, never in an address or a log.
 */
import type {
  NoticeCategory,
  PushFamily,
  PushSubscribeIn,
  PushSystem,
  PushUnsubscribeIn,
} from "@/lib/api/v1/types_push";
import { installPlatform, isStandalone } from "@/lib/pwa";

export type PushSupport = "supported" | "needs_install" | "unsupported";
/** This browser for PrediGol's notices: cannot, must be installed first, blocked by the reader, receiving, or not yet. */
export type DeviceStatus = "unsupported" | "needs_install" | "denied" | "on" | "off";

interface SubscriptionLike {
  endpoint: string;
  options?: { applicationServerKey?: ArrayBuffer | null };
  toJSON: () => { endpoint?: string; keys?: Record<string, string | undefined> };
  unsubscribe: () => Promise<boolean>;
}

interface RegistrationLike {
  pushManager: {
    getSubscription: () => Promise<SubscriptionLike | null>;
    subscribe: (options: {
      userVisibleOnly: boolean;
      applicationServerKey: Uint8Array<ArrayBuffer>;
    }) => Promise<SubscriptionLike>;
  };
}

/** The parts of `window` this module reads: a test hands it a stand-in. */
export interface PushHost {
  navigator: {
    userAgent: string;
    maxTouchPoints?: number;
    standalone?: boolean;
    serviceWorker?: { getRegistration: () => Promise<RegistrationLike | undefined> };
  };
  matchMedia?: (query: string) => { matches: boolean };
  Notification?: {
    permission: NotificationPermission;
    requestPermission: () => Promise<NotificationPermission>;
  };
  PushManager?: unknown;
  localStorage?: Pick<Storage, "getItem" | "setItem" | "removeItem">;
}

function host(): PushHost | undefined {
  return typeof window === "undefined" ? undefined : (window as unknown as PushHost);
}

export function pushSupport(win: PushHost | undefined = host()): PushSupport {
  if (!win) return "unsupported";
  const ios = installPlatform(win.navigator) === "ios";
  if (ios && !isStandalone(win)) return "needs_install";
  if (!win.navigator.serviceWorker || !win.PushManager || !win.Notification) return "unsupported";
  return "supported";
}

/** The browser's family, from its user agent; an iPhone's installed app is Safari's (its user agent does not say). */
export function browserFamily(ua: string, touchPoints = 0): PushFamily {
  if (browserSystem(ua, touchPoints) === "ios") return "safari";
  if (/Edg(e|A|iOS)?\//.test(ua)) return "edge";
  if (/Firefox\/|FxiOS\//.test(ua)) return "firefox";
  if (/OPR\/|SamsungBrowser\//.test(ua)) return "other";
  if (/Chrome\/|CriOS\//.test(ua)) return "chrome";
  if (/Safari\//.test(ua)) return "safari";
  return "other";
}

export function browserSystem(ua: string, touchPoints = 0): PushSystem {
  if (/iPhone|iPad|iPod/.test(ua) || (/Macintosh/.test(ua) && touchPoints > 1)) return "ios";
  if (/Android/.test(ua)) return "android";
  if (/Windows/.test(ua)) return "windows";
  if (/Mac OS X|Macintosh/.test(ua)) return "macos";
  if (/Linux|CrOS/.test(ua)) return "linux";
  return "other";
}

/** PrediGol's public key (base64url, as GET /me/push gives it) in the bytes the browser subscribes with. */
export function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const padded = base64url
    .replace(/-/g, "+")
    .replace(/_/g, "/")
    .padEnd(Math.ceil(base64url.length / 4) * 4, "=");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

/** Whether a subscription was made with this key (after the owner changes PrediGol's key, it must be made again). */
export function sameKey(current: ArrayBuffer | null | undefined, key: Uint8Array): boolean {
  if (!current) return false;
  const a = new Uint8Array(current);
  return a.length === key.length && a.every((byte, i) => byte === key[i]);
}

const DEVICE_KEY = "predigol.push.device";

export interface RememberedDevice {
  id: number;
  endpoint: string;
}

export function rememberedDevice(win: PushHost | undefined = host()): RememberedDevice | null {
  try {
    const raw = win?.localStorage?.getItem(DEVICE_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<RememberedDevice>;
    return typeof value.id === "number" && typeof value.endpoint === "string"
      ? { id: value.id, endpoint: value.endpoint }
      : null;
  } catch {
    return null;
  }
}

function remember(device: RememberedDevice | null, win: PushHost | undefined): void {
  try {
    if (device) win?.localStorage?.setItem(DEVICE_KEY, JSON.stringify(device));
    else win?.localStorage?.removeItem(DEVICE_KEY);
  } catch {
    // storage refused: this browser will not know it is one of the account's devices, and says «off»
  }
}

export interface PushApi {
  subscribe: (body: PushSubscribeIn) => Promise<{ id: number }>;
  unsubscribe: (body: PushUnsubscribeIn) => Promise<void>;
}

export type EnableResult =
  | { ok: true; deviceId: number }
  | { ok: false; reason: "unsupported" | "denied" | "dismissed" | "failed"; error?: unknown };

async function registration(win: PushHost): Promise<RegistrationLike | undefined> {
  try {
    return await win.navigator.serviceWorker?.getRegistration();
  } catch {
    return undefined;
  }
}

function bodyOf(sub: SubscriptionLike, win: PushHost): PushSubscribeIn | null {
  const json = sub.toJSON();
  const p256dh = json.keys?.["p256dh"];
  const auth = json.keys?.["auth"];
  if (!json.endpoint || !p256dh || !auth) return null;
  const ua = win.navigator.userAgent;
  const touch = win.navigator.maxTouchPoints ?? 0;
  return {
    endpoint: json.endpoint,
    keys: { p256dh, auth },
    family: browserFamily(ua, touch),
    system: browserSystem(ua, touch),
    installed: isStandalone(win),
  };
}

/**
 * Called from the reader's tap on «Activar avisos»: the browser's own question first (while the tap lasts), then the
 * subscription with PrediGol's key, then the server. A subscription made with another key is made again.
 */
export async function enableOnThisDevice(
  publicKey: string,
  api: PushApi,
  win: PushHost | undefined = host(),
): Promise<EnableResult> {
  if (!win || pushSupport(win) !== "supported" || !win.Notification) {
    return { ok: false, reason: "unsupported" };
  }
  let permission = win.Notification.permission;
  if (permission === "default") {
    try {
      permission = await win.Notification.requestPermission();
    } catch (error) {
      return { ok: false, reason: "failed", error };
    }
  }
  if (permission === "denied") return { ok: false, reason: "denied" };
  if (permission !== "granted") return { ok: false, reason: "dismissed" };
  const reg = await registration(win);
  if (!reg) return { ok: false, reason: "unsupported" };
  try {
    const key = keyBytes(publicKey);
    let sub = await reg.pushManager.getSubscription();
    if (sub && !sameKey(sub.options?.applicationServerKey, key)) {
      await sub.unsubscribe().catch(() => false);
      sub = null;
    }
    sub ??= await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key });
    const body = bodyOf(sub, win);
    if (!body) return { ok: false, reason: "failed" };
    const device = await api.subscribe(body);
    remember({ id: device.id, endpoint: body.endpoint }, win);
    return { ok: true, deviceId: device.id };
  } catch (error) {
    return { ok: false, reason: "failed", error };
  }
}

/** This browser stops receiving: the server revokes it and the browser forgets the subscription. */
export async function disableOnThisDevice(
  api: PushApi,
  win: PushHost | undefined = host(),
): Promise<void> {
  if (!win) return;
  const reg = await registration(win);
  const sub = reg ? await reg.pushManager.getSubscription().catch(() => null) : null;
  const known = rememberedDevice(win);
  if (sub) await api.unsubscribe({ endpoint: sub.endpoint });
  else if (known) await api.unsubscribe({ device_id: known.id });
  if (sub) await sub.unsubscribe().catch(() => false);
  remember(null, win);
}

export interface DeviceState {
  status: DeviceStatus;
  /** The account's device this browser is, while it receives. */
  deviceId: number | null;
  /** The push service gave this browser a new address since it was subscribed: told to the server again. */
  moved: PushSubscribeIn | null;
}

/** What this browser is now, given the account's live devices (GET /me/push). */
export async function deviceState(
  liveIds: readonly number[],
  win: PushHost | undefined = host(),
): Promise<DeviceState> {
  const support = pushSupport(win);
  if (!win || support !== "supported") {
    return {
      status: support === "needs_install" ? "needs_install" : "unsupported",
      deviceId: null,
      moved: null,
    };
  }
  const permission = win.Notification?.permission ?? "default";
  if (permission === "denied") return { status: "denied", deviceId: null, moved: null };
  const reg = await registration(win);
  if (!reg) return { status: "unsupported", deviceId: null, moved: null };
  const known = rememberedDevice(win);
  const sub = await reg.pushManager.getSubscription().catch(() => null);
  if (permission !== "granted" || !sub || !known || !liveIds.includes(known.id)) {
    return { status: "off", deviceId: null, moved: null };
  }
  const moved = sub.endpoint !== known.endpoint ? bodyOf(sub, win) : null;
  return { status: "on", deviceId: known.id, moved };
}

/** The new address told to the server: the same device, still receiving. */
export async function followMovedSubscription(
  body: PushSubscribeIn,
  api: PushApi,
  win: PushHost | undefined = host(),
): Promise<void> {
  const device = await api.subscribe(body);
  remember({ id: device.id, endpoint: body.endpoint }, win);
}

/**
 * The product events' name for a notice's category (notification_opened, notification_enabled and
 * notification_disabled): the reader's own test is not counted.
 */
export function eventCategory(category: string | null): Exclude<NoticeCategory, "test"> | null {
  switch (category) {
    case "result":
    case "lineup":
    case "digest":
    case "reminder":
    case "account":
      return category;
    default:
      return null;
  }
}

/** The page the notice opened, without the notice's mark (sw.js adds ?notice=<category> to count the opening). */
export function withoutNoticeMark(search: string): string {
  const params = new URLSearchParams(search);
  params.delete("notice");
  const rest = params.toString();
  return rest ? `?${rest}` : "";
}
