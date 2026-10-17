/**
 * The demo adapter's helper. Live data does not go through here: it is read
 * from the FastAPI service by src/lib/api/v1, and every page that shows it is
 * labelled LIVE by what it actually renders (see components/system/DataSources).
 */

/** Simulates network latency so loading states are exercised in demo mode. */
export function demo<T>(value: T, ms = 120): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value), ms));
}
