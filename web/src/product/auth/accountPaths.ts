/**
 * The pages that get a reader in without the owner (plan UX, A7): public, and shown whatever the session - a link
 * opened while signed in (as the same account or another) still works, and the page says what happens.
 */
export const ACCOUNT_PATHS = [
  "/activate",
  "/forgot-password",
  "/reset-password",
  "/unlock",
] as const;

export function isAccountPath(path: string): boolean {
  return (ACCOUNT_PATHS as readonly string[]).includes(path.replace(/\/+$/, "") || "/");
}
