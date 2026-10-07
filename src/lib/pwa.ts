/**
 * The installable app (PWA): public/manifest.webmanifest and public/sw.js.
 *
 * The service worker is registered in production builds only. In development it would keep the dev server's
 * modules in a cache and serve old code after an edit. It is registered once the page has loaded, so it never
 * competes with the first paint, and a failure to register is reported to the console and changes nothing
 * else: the site works the same without it.
 */
export const SERVICE_WORKER_URL = "/sw.js";

interface ServiceWorkerHost {
  serviceWorker?: { register: (url: string, options?: { scope?: string }) => Promise<unknown> };
}

export async function registerServiceWorker(
  host: ServiceWorkerHost | undefined = typeof navigator === "undefined" ? undefined : navigator,
  production: boolean = import.meta.env.PROD,
): Promise<boolean> {
  if (!production || !host?.serviceWorker) return false;
  try {
    await host.serviceWorker.register(SERVICE_WORKER_URL, { scope: "/" });
    return true;
  } catch (error) {
    console.warn("PrediGol: the service worker could not be registered", error);
    return false;
  }
}
