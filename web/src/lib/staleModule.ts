/**
 * A page that asks for a script the server no longer has (closing plan 5.3): after a deploy, an open tab holds the old
 * version's file names. The browser says so in a few ways; this knows them, and the one event the page raises when a
 * reload alone did not mend it, so that an offer to reload can be shown.
 */
const STALE =
  /failed to fetch dynamically imported module|error loading dynamically imported module|importing a module script failed|unable to preload css|loading (css )?chunk [\w-]+ failed|failed to load module script/i;

export const STALE_EVENT = "predigol:stale-module";

export function isStaleModuleError(error: unknown): boolean {
  if (error instanceof Error) return error.name === "ChunkLoadError" || STALE.test(error.message);
  return typeof error === "string" && STALE.test(error);
}
