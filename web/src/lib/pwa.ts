/**
 * The installable app (PWA): public/manifest.webmanifest and public/sw.js.
 *
 * The service worker is registered in production builds only. In development it would keep the dev server's
 * modules in a cache and serve old code after an edit. It is registered once the page has loaded, so it never
 * competes with the first paint, and a failure to register is reported to the console and changes nothing
 * else: the site works the same without it.
 *
 * Updates are controlled: a new worker waits until the reader accepts (UPDATE_EVENT -> applyUpdate), the page
 * looks for a new version every 30 minutes and whenever it comes back to the foreground, and a script chunk of a
 * version that no longer exists on the server reloads the page once instead of breaking it.
 *
 * Installing (plan UX, A15, section 35): whether PrediGol runs as the installed app (isStandalone), which device's steps
 * «Instalar PrediGol» shows first (installPlatform, installOrder), and the once-per-device mark of the first opening
 * in installed mode that the product event pwa_installed counts (markInstalledOnce). The guided install with Android's
 * own prompt is B7's.
 */
export const SERVICE_WORKER_URL = "/sw.js";
/** Fired on window when a new version is installed and waiting; detail: the waiting worker. */
export const UPDATE_EVENT = "predigol:update-ready";
const CHECK_EVERY_MS = 30 * 60 * 1000;
const RELOAD_KEY = "predigol.chunkReloadAt";

interface WorkerLike {
  state?: string;
  postMessage: (message: unknown) => void;
  addEventListener?: (type: "statechange", listener: () => void) => void;
}

interface RegistrationLike {
  waiting?: WorkerLike | null;
  installing?: WorkerLike | null;
  update?: () => Promise<unknown>;
  addEventListener?: (type: "updatefound", listener: () => void) => void;
}

interface ServiceWorkerHost {
  serviceWorker?: {
    register: (url: string, options?: { scope?: string }) => Promise<unknown>;
    controller?: unknown;
    addEventListener?: (type: "controllerchange", listener: () => void) => void;
  };
}

function announce(worker: WorkerLike): void {
  if (typeof window !== "undefined")
    window.dispatchEvent(new CustomEvent(UPDATE_EVENT, { detail: worker }));
}

/** A new version waiting while an older one controls this page: tell the page. (A first install never waits.) */
export function watchForUpdates(
  registration: RegistrationLike,
  host: ServiceWorkerHost,
  onReady: (worker: WorkerLike) => void = announce,
): void {
  const container = host.serviceWorker;
  if (registration.waiting && container?.controller) onReady(registration.waiting);
  registration.addEventListener?.("updatefound", () => {
    const installing = registration.installing;
    installing?.addEventListener?.("statechange", () => {
      if (installing.state === "installed" && container?.controller) onReady(installing);
    });
  });
  if (typeof window === "undefined" || !registration.update) return;
  const check = () => void registration.update?.().catch(() => undefined);
  window.setInterval(check, CHECK_EVERY_MS);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") check();
  });
}

export async function registerServiceWorker(
  host: ServiceWorkerHost | undefined = typeof navigator === "undefined" ? undefined : navigator,
  production: boolean = import.meta.env.PROD,
): Promise<boolean> {
  if (!production || !host?.serviceWorker) return false;
  try {
    const registration = (await host.serviceWorker.register(SERVICE_WORKER_URL, {
      scope: "/",
    })) as RegistrationLike | undefined;
    if (registration) watchForUpdates(registration, host);
    reloadOnStaleChunks();
    return true;
  } catch (error) {
    console.warn("PrediGol: the service worker could not be registered", error);
    return false;
  }
}

/** The reader accepted: the waiting worker takes over and the page reloads once, on the new version. */
export function applyUpdate(worker: WorkerLike, host: ServiceWorkerHost = navigator): void {
  let reloaded = false;
  host.serviceWorker?.addEventListener?.("controllerchange", () => {
    if (reloaded) return;
    reloaded = true;
    window.location.reload();
  });
  worker.postMessage({ type: "SKIP_WAITING" });
}

interface DisplayHost {
  matchMedia?: (query: string) => { matches: boolean };
  navigator?: { standalone?: boolean; userAgent?: string; maxTouchPoints?: number };
}

/** Whether PrediGol runs as the installed app (from the home screen icon), not in a browser tab. */
export function isStandalone(
  win: DisplayHost | undefined = typeof window === "undefined" ? undefined : window,
): boolean {
  if (!win) return false;
  // Safari on iPhone says so in navigator.standalone; every other browser in the display mode.
  if (win.navigator?.standalone === true) return true;
  return (
    typeof win.matchMedia === "function" && win.matchMedia("(display-mode: standalone)").matches
  );
}

export type InstallPlatform = "ios" | "android" | "other";

/** Which install steps come first in «Más» (plan UX, A15): an iPhone or iPad, an Android, or anything else. */
export function installPlatform(
  nav: { userAgent?: string; maxTouchPoints?: number } | undefined = typeof navigator ===
  "undefined"
    ? undefined
    : navigator,
): InstallPlatform {
  const ua = nav?.userAgent ?? "";
  if (/iPhone|iPad|iPod/i.test(ua)) return "ios";
  // An iPad asking for the desktop site says "Macintosh", but it has a touch screen.
  if (/Macintosh/i.test(ua) && (nav?.maxTouchPoints ?? 0) > 1) return "ios";
  if (/Android/i.test(ua)) return "android";
  return "other";
}

const PLATFORMS: readonly InstallPlatform[] = ["ios", "android", "other"];

/** This device's steps first, the other two after them: a reader may be installing on another device. */
export function installOrder(first: InstallPlatform): InstallPlatform[] {
  return [first, ...PLATFORMS.filter((p) => p !== first)];
}

const INSTALLED_KEY = "predigol.pwa_installed";

/**
 * True the first time the installed app opens on this device (plan UX, section 35: pwa_installed is «the appinstalled
 * event or the first opening in installed mode»; the first opening is the one rule that also works on an iPhone,
 * which never fires appinstalled). Remembered in the app's own storage; without storage it never says yes, so a
 * reader who refuses storage is not counted again and again.
 */
export function markInstalledOnce(storage?: Pick<Storage, "getItem" | "setItem"> | null): boolean {
  try {
    // Reading window.localStorage itself throws where storage is refused, so it is read inside the try.
    const store = storage ?? (typeof window === "undefined" ? null : window.localStorage);
    if (!store) return false;
    if (store.getItem(INSTALLED_KEY)) return false;
    store.setItem(INSTALLED_KEY, new Date().toISOString().slice(0, 10));
    return store.getItem(INSTALLED_KEY) !== null;
  } catch {
    return false;
  }
}

/** After a deploy, an open tab may ask for a script chunk the server no longer has: reload once (not in a loop). */
export function reloadOnStaleChunks(): void {
  if (typeof window === "undefined") return;
  window.addEventListener("vite:preloadError", (event) => {
    let last = 0;
    try {
      last = Number(window.sessionStorage.getItem(RELOAD_KEY) ?? "0");
    } catch {
      /* storage unavailable */
    }
    if (Date.now() - last < 30_000) return;
    try {
      window.sessionStorage.setItem(RELOAD_KEY, String(Date.now()));
    } catch {
      /* storage unavailable */
    }
    event.preventDefault();
    window.location.reload();
  });
}
