/**
 * Without a connection (plan de Inicio, 4.1, PWA): Inicio shows what it last loaded - the queries keep their data and wait for
 * the network instead of failing - and one small line says so, in place of six cards of error. The service worker never keeps
 * an answer of the API, so what is shown is only what this open page already had.
 */
import { WifiOff } from "lucide-react";
import { useSyncExternalStore } from "react";
import { t } from "@/lib/i18n";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

/** Whether the browser says it is online; the server and the first paint say yes. */
export function useOnline(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => navigator.onLine,
    () => true,
  );
}

export function OfflineNote() {
  if (useOnline()) return null;
  return (
    <p
      role="status"
      data-testid="offline-note"
      className="flex items-center gap-2 rounded-lg border border-warning/40 bg-warning-soft px-3 py-2 text-sm text-warning"
    >
      <WifiOff aria-hidden className="h-4 w-4 shrink-0" />
      {t("home.offline")}
    </p>
  );
}
