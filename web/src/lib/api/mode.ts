/**
 * Where the data on screen comes from.
 *
 *   VITE_DATA_MODE=mock    every page renders the demo adapter (src/mock)
 *   VITE_DATA_MODE=live    every page reads the FastAPI service; a page the
 *                          backend cannot serve yet says so instead of
 *                          falling back to demo data
 *   VITE_DATA_MODE=hybrid  live where the backend serves it, demo elsewhere;
 *                          any page that mixes the two is labelled HYBRID
 *
 * VITE_API_BASE_URL points at the API, e.g. http://localhost:8010. Without it
 * the mode is forced to mock: there is nothing live to read.
 */

export type DataMode = "mock" | "live" | "hybrid";

export const API_BASE_URL: string = (
  (import.meta.env["VITE_API_BASE_URL"] as string | undefined) ?? ""
).replace(/\/+$/, "");

function resolveMode(): DataMode {
  const raw = (import.meta.env["VITE_DATA_MODE"] as string | undefined)?.trim().toLowerCase();
  if (!API_BASE_URL) return "mock";
  if (raw === "live" || raw === "hybrid" || raw === "mock") return raw;
  return "live";
}

export const DATA_MODE: DataMode = resolveMode();

/** True when a page may call the backend at all. */
export const LIVE_ENABLED = DATA_MODE !== "mock";
