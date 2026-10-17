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
