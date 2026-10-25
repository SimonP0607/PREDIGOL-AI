/**
 * The web's errors to Sentry (plan UX, A2) - through our own API, never to Sentry itself: the browser posts its
 * events to /api/v1/monitoring/envelope, the server filters each one again (fbi.core.sentry) and forwards it, so
 * the reader's address never reaches a third party and the page's security policy needs no new origin. Off until the
 * server says it is on (/api/v1/monitoring/client): the SDK is not even downloaded then.
 *
 * What goes: the error (type, message without values, frames), the page's route without its query, the release,
 * the request id of a failed API call, the browser's name, the screen width, whether it is the installed app or a
 * tab, and the account's pseudonym (an HMAC the server computes; never the id or the email). Never: emails,
 * passwords, tokens, cookies, picks, what a person typed or clicked - this filter runs here first, the server's
 * after it.
 */
import type { Breadcrumb, ErrorEvent } from "@sentry/browser";

type Sdk = typeof import("@sentry/browser");

export interface MonitoringConfig {
  enabled: boolean;
  dsn: string | null;
  environment: string;
  tunnel: string;
}

const RELEASE = `predigol-web@${(import.meta.env["VITE_APP_VERSION"] as string | undefined) ?? "dev"}`;
const PSEUDONYM = /^[0-9a-f]{20}$/;
const EMAIL = /[\w.%+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}/gu;
const TOKEN = /(?<![\w-])(?=[\w-]*[A-Z])(?=[\w-]*[a-z])[\w-]{32,}(?![\w-])/g;
const HEX = /(?<![0-9a-f])[0-9a-f]{32,}(?![0-9a-f])/g;
const QUOTED = /'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"/g;
const SENSITIVE =
  /(pass(word|wd)?|secret|token|cookie|authori[sz]ation|session|e-?mail|phone|dsn|csrf|totp|otp|recovery|api[-_]?key|^key$|^code$|^body$|^data$)/i;
const DROPPED = new Set(["console", "ui.click", "ui.input", "ui.keypress", "sentry.event"]);
/** Default integrations of the SDK that are left out: sessions, console breadcrumbs, the reader's locale and time
 * zone, AI conversation ids - and the default breadcrumbs, replaced by ones without clicks. */
const LEFT_OUT = new Set([
  "BrowserSession",
  "Breadcrumbs",
  "Console",
  "CultureContext",
  "ConversationId",
]);
const MAX = 300;

let sdk: Sdk | null = null;
let starting: Promise<boolean> | null = null;
let observed: string | null = null;

/** At most ``n`` UTF-16 units, never half of a character (a cut emoji would make the event unreadable). */
function cut(text: string, n: number): string {
  if (text.length <= n) return text;
  const head = text.slice(0, n);
  const last = head.charCodeAt(head.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? head.slice(0, -1) : head;
}

/** One line of text as it may leave the browser: the first line, emails and tokens out, quoted values out. */
export function scrubText(text: string, quoted = true): string {
  const first = cut(text.trim().split("\n")[0] ?? "", 1000);
  const plain = quoted ? first.replace(QUOTED, "<value>") : first;
  return cut(plain.replace(EMAIL, "<email>").replace(TOKEN, "<token>").replace(HEX, "<hex>"), MAX);
}

/** A URL without its query string, its fragment or a user:password. */
export function cleanUrl(url: string): string {
  try {
    const parsed = new URL(url, "https://predigol.invalid");
    const path = scrubText(parsed.pathname, false);
    return url.startsWith("/") ? path : `${parsed.protocol}//${parsed.host}${path}`;
  } catch {
    return "";
  }
}

function clean(value: unknown, depth = 0): unknown {
  if (depth > 6) return undefined;
  if (typeof value === "string") return scrubText(value);
  if (Array.isArray(value)) return value.slice(0, 50).map((v) => clean(v, depth + 1));
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) {
      if (!SENSITIVE.test(k)) out[k] = clean(v, depth + 1);
    }
    return out;
  }
  return value;
}

export function scrubBreadcrumb(crumb: Breadcrumb): Breadcrumb | null {
  const category = crumb.category ?? "";
  if (DROPPED.has(category)) return null;
  const out: Breadcrumb = {};
  if (crumb.timestamp !== undefined) out.timestamp = crumb.timestamp;
  if (crumb.type !== undefined) out.type = crumb.type;
  if (crumb.category !== undefined) out.category = crumb.category;
  if (crumb.level !== undefined) out.level = crumb.level;
  if (typeof crumb.message === "string") out.message = scrubText(crumb.message);
  const data = crumb.data;
  if (data && typeof data === "object") {
    if (crumb.type === "http" || category === "fetch" || category === "xhr") {
      const kept: Record<string, unknown> = {};
      for (const key of ["method", "status_code"]) if (key in data) kept[key] = data[key];
      if (typeof data["url"] === "string") kept["url"] = cleanUrl(data["url"]);
      out.data = kept;
    } else if (category === "navigation") {
      const kept: Record<string, unknown> = {};
      for (const key of ["from", "to"]) {
        if (typeof data[key] === "string") kept[key] = cleanUrl(data[key] as string);
      }
      out.data = kept;
    } else {
      out.data = clean(data) as Record<string, unknown>;
    }
  }
  return out;
}

/** The event as it may leave the browser (``beforeSend``). The server runs its own filter after this one. */
export function scrubEvent(event: ErrorEvent): ErrorEvent | null {
  try {
    if (event.request) {
      const agent = event.request.headers?.["User-Agent"] ?? event.request.headers?.["user-agent"];
      event.request = {
        ...(event.request.url ? { url: cleanUrl(event.request.url) } : {}),
        ...(agent ? { headers: { "User-Agent": agent.slice(0, MAX) } } : {}),
      };
    }
    const id = event.user?.id;
    if (typeof id === "string" && PSEUDONYM.test(id)) event.user = { id };
    else delete event.user;
    for (const item of event.exception?.values ?? []) {
      if (item.type === "KeyError") item.value = "";
      else if (typeof item.value === "string") item.value = scrubText(item.value);
      for (const frame of item.stacktrace?.frames ?? []) {
        delete frame.vars;
        // the first frame of a browser error is often the page's own address, query string included
        if (frame.filename?.includes("://")) frame.filename = cleanUrl(frame.filename);
        if (frame.abs_path?.includes("://")) frame.abs_path = cleanUrl(frame.abs_path);
      }
    }
    if (typeof event.message === "string") event.message = scrubText(event.message);
    if (event.breadcrumbs) {
      event.breadcrumbs = event.breadcrumbs
        .map(scrubBreadcrumb)
        .filter((c): c is Breadcrumb => c !== null);
    }
    if (event.extra) event.extra = clean(event.extra) as Record<string, unknown>;
    if (event.tags) event.tags = clean(event.tags) as NonNullable<ErrorEvent["tags"]>;
    return event;
  } catch {
    return null;
  }
}

/** What the page says about the device: its width, and whether it is the installed app or a tab. */
export function deviceTags(win: Pick<Window, "innerWidth" | "matchMedia">): Record<string, string> {
  let display = "browser";
  try {
    if (win.matchMedia("(display-mode: standalone)").matches) display = "app";
  } catch {
    // an old browser without display-mode: a tab
  }
  return { viewport: String(Math.round(win.innerWidth)), display };
}

async function defaultConfig(): Promise<MonitoringConfig | null> {
  const res = await fetch("/api/v1/monitoring/client", {
    headers: { accept: "application/json" },
    credentials: "same-origin",
  });
  return res.ok ? ((await res.json()) as MonitoringConfig) : null;
}

/**
 * Switch reporting on when the server says so. Once per page; never throws (reporting errors is not worth a
 * crash). ``readConfig`` and ``load`` are for tests.
 */
export function startObservability(
  readConfig: () => Promise<MonitoringConfig | null> = defaultConfig,
  load: () => Promise<Sdk> = () => import("@sentry/browser"),
): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  starting ??= (async () => {
    try {
      const cfg = await readConfig();
      if (!cfg?.enabled || !cfg.dsn) return false;
      const module = await load();
      module.init({
        dsn: cfg.dsn,
        tunnel: cfg.tunnel,
        environment: cfg.environment,
        release: RELEASE,
        // what the SDK may collect by itself: no user, no cookies, no headers but the browser's name, no bodies, no
        // query strings, no frame variables (its defaults collect all of these)
        dataCollection: {
          userInfo: false,
          cookies: false,
          httpHeaders: { request: { allow: ["user-agent"] }, response: false },
          httpBodies: [],
          urlQueryParams: false,
          graphQL: { document: false, variables: false },
          genAI: { inputs: false, outputs: false },
          mcp: { inputs: false, outputs: false },
          databaseQueryData: false,
          queues: false,
          stackFrameVariables: false,
        },
        maxBreadcrumbs: 30,
        sendClientReports: false,
        // the errors only: no sessions, no tracing, no replay, no console lines, no clicks, no locale
        integrations: (defaults) => [
          ...defaults.filter((i) => !LEFT_OUT.has(i.name)),
          module.breadcrumbsIntegration({ dom: false, sentry: false }),
        ],
        beforeSend: (event) => scrubEvent(event),
        beforeBreadcrumb: (crumb) => scrubBreadcrumb(crumb),
        // the API refuses a state-changing request without it (fbi.api.security.same_site_only)
        transportOptions: { headers: { "x-requested-with": "predigol" } },
        initialScope: { tags: deviceTags(window) },
      });
      sdk = module;
      if (observed) module.setUser({ id: observed });
      return true;
    } catch {
      return false;
    }
  })();
  return starting;
}

/** The signed-in account's pseudonym (from /auth/me), or null on signing out. */
export function setObservedUser(id: string | null | undefined): void {
  observed = id && PSEUDONYM.test(id) ? id : null;
  sdk?.setUser(observed ? { id: observed } : null);
}

/** An error a boundary caught (the page crashed): to Sentry, with where it was caught. */
export function reportError(error: unknown, boundary: string): void {
  sdk?.captureException(error, { tags: { boundary, route: cleanUrl(window.location.pathname) } });
}

/** A failed call to our API (5xx): its request id ties the browser's event to the server's log line. */
export function reportApiFailure(info: {
  status: number;
  code: string;
  requestId: string | null;
  method: string;
  path: string;
}): void {
  if (!sdk || info.status < 500) return;
  sdk.captureMessage(`API ${info.status} ${info.method} ${cleanUrl(info.path)}`, {
    level: "error",
    tags: {
      request_id: info.requestId ?? "-",
      status: String(info.status),
      error_code: info.code,
      route: cleanUrl(window.location.pathname),
    },
  });
}

/** For the owner's test from the console (plan UX, A2): an error raised on purpose in the browser. */
export async function reportTestError(): Promise<boolean> {
  if (!sdk) return false;
  sdk.captureException(
    new Error("PrediGol monitoring test (A2): raised on purpose in the browser"),
    {
      tags: { boundary: "console-test" },
    },
  );
  return sdk.flush(5000);
}

/** For tests: forget what was started. */
export function resetObservabilityForTests(): void {
  sdk = null;
  starting = null;
  observed = null;
}
