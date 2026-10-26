/**
 * What a ticket carries besides the reader's words (plan UX, A14; section 32: «contexto automático»): the screen's path
 * without its query, the request id of the last API error this page met, the web's version, the device's class and
 * whether it is the installed app - the same shapes the server checks again (fbi.customer.support.clean_context).
 * Never a password, a token, an address, a query string or what a form held; a one-use link's page keeps only its name.
 */
import { lastApiError } from "@/lib/api/v1/client";
import type { SupportContext, SupportDevice } from "@/lib/api/v1/types_support";

const VERSION = (import.meta.env["VITE_APP_VERSION"] as string | undefined) ?? "dev";
const ROUTE = /^\/[A-Za-z0-9/_.$-]{0,199}$/;
const REQUEST_ID = /^[A-Za-z0-9]{1,32}$/;
const SHAPE_VERSION = /^[A-Za-z0-9._+-]{1,40}$/;
/** The pages of the one-use links (plan UX, A7): only the page, never what follows it. */
const LINK_PAGES = ["/activate", "/reset-password", "/unlock"] as const;

/** A phone below 640 px, a tablet below 1024 px, a computer from there (the product's own breakpoints). */
export function deviceClass(width: number): SupportDevice {
  return width < 640 ? "phone" : width < 1024 ? "tablet" : "desktop";
}

/** The screen as a path the server keeps: no query, no fragment, nothing but plain path characters; null otherwise. */
export function routeOf(pathname: string): string | null {
  const path = (pathname.split(/[?#]/)[0] ?? "").replace(/[^A-Za-z0-9/_.$-]/g, "").slice(0, 200);
  const page = LINK_PAGES.find((p) => path === p || path.startsWith(`${p}/`));
  const route = page ?? path;
  return ROUTE.test(route) ? route : null;
}

export interface ContextOptions {
  /** The match a «wrong data» report is about. */
  matchId?: number | undefined;
  /** An error's own request id (an ErrorState knows the one it shows); else the last one the page met. */
  requestId?: string | null | undefined;
}

type Win = Pick<Window, "innerWidth" | "matchMedia"> & { location: Pick<Location, "pathname"> };

export function buildContext(options: ContextOptions = {}, win: Win = window): SupportContext {
  const context: SupportContext = { device: deviceClass(win.innerWidth) };
  const route = routeOf(win.location.pathname);
  if (route) context.route = route;
  const rid = options.requestId ?? lastApiError();
  if (rid && REQUEST_ID.test(rid)) context.request_id = rid;
  if (SHAPE_VERSION.test(VERSION)) context.web_version = VERSION;
  try {
    context.pwa = win.matchMedia("(display-mode: standalone)").matches;
  } catch {
    context.pwa = false; // an old browser without display-mode: a tab
  }
  if (options.matchId !== undefined && Number.isInteger(options.matchId) && options.matchId > 0) {
    context.match_id = options.matchId;
  }
  return context;
}
