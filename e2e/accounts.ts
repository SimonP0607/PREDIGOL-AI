/**
 * The QA accounts the suite signs in with. Their passwords are generated on the
 * machine by `python -m scripts.create_user --generate --out ~/.fbi/qa-<name>.txt`
 * (mode 0600) and are never in Git: this reads them from those files, or from
 * E2E_<NAME>_EMAIL / E2E_<NAME>_PASSWORD when set.
 */
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export type AccountName = "admin" | "user" | "userEn" | "switch" | "target";

/** Which file holds each account, and the role and language the suite expects it to have. */
export const ACCOUNTS: Record<
  AccountName,
  { file: string; role: "SUPER_ADMIN" | "USER"; lang: "es" | "en"; tz: string }
> = {
  admin: { file: "qa-admin.txt", role: "SUPER_ADMIN", lang: "en", tz: "UTC" },
  user: { file: "qa-user.txt", role: "USER", lang: "es", tz: "America/Bogota" },
  userEn: { file: "qa-user-en.txt", role: "USER", lang: "en", tz: "Europe/Madrid" },
  switch: { file: "qa-switch.txt", role: "USER", lang: "es", tz: "America/Bogota" },
  target: { file: "qa-target.txt", role: "USER", lang: "es", tz: "UTC" },
};

const DIR = process.env["E2E_ACCOUNTS_DIR"] ?? join(homedir(), ".fbi");

export function credentials(name: AccountName): { email: string; password: string } {
  const env = name.replace(/[A-Z]/g, (c) => `_${c}`).toUpperCase();
  const email = process.env[`E2E_${env}_EMAIL`];
  const password = process.env[`E2E_${env}_PASSWORD`];
  if (email && password) return { email, password };
  const path = join(DIR, ACCOUNTS[name].file);
  if (!existsSync(path)) {
    throw new Error(
      `No credentials for the "${name}" QA account: create it with scripts/create_user.py --generate --out ${path}`,
    );
  }
  const fields = Object.fromEntries(
    readFileSync(path, "utf8")
      .split("\n")
      .filter((l) => l.includes(": "))
      .map((l) => [l.slice(0, l.indexOf(": ")), l.slice(l.indexOf(": ") + 2).trim()]),
  );
  if (!fields["email"] || !fields["password"])
    throw new Error(`${path} has no email/password lines`);
  return { email: fields["email"], password: fields["password"] };
}

export function statePath(name: AccountName): string {
  return join(import.meta.dirname, ".auth", `${name}.json`);
}
