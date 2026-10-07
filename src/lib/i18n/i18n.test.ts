/// <reference types="bun" />
/**
 * Every key exists in Spanish AND English, and every key the code asks for exists.
 * A missing key falls back (other language, then the key) instead of breaking a page.
 */
import { describe, expect, test } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { CATALOGS, type Catalog } from "./catalogs";
import { hasKey, setLocale, translate } from "./index";

function keys(node: Catalog, prefix = ""): string[] {
  return Object.entries(node).flatMap(([k, v]) =>
    typeof v === "string" ? [`${prefix}${k}`] : keys(v, `${prefix}${k}.`),
  );
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "locales" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !name.endsWith(".test.ts") ? [path] : [];
  });
}

const PLURAL = /_(zero|one|two|few|many|other)$/;

describe("catalogs", () => {
  const es = new Set(keys(CATALOGS.es));
  const en = new Set(keys(CATALOGS.en));

  test("Spanish and English have exactly the same keys", () => {
    const onlyEs = [...es].filter((k) => !en.has(k));
    const onlyEn = [...en].filter((k) => !es.has(k));
    expect({ onlyEs, onlyEn }).toEqual({ onlyEs: [], onlyEn: [] });
  });

  test("placeholders use one brace: {name} (a {{name}} rendered as {value} on the player page)", () => {
    const doubled = [
      ...keys(CATALOGS.es).map((k) => `es ${k}`),
      ...keys(CATALOGS.en).map((k) => `en ${k}`),
    ].filter((entry) => {
      const [locale, key] = entry.split(" ") as ["es" | "en", string];
      return /\{\{\w+\}\}/.test(translate(key, undefined, locale));
    });
    expect(doubled).toEqual([]);
    expect(
      translate("catalog.players.detail.profile.clubFromSquad", { team: "Deportivo Pasto" }, "es"),
    ).toBe("Deportivo Pasto (plantilla)");
  });

  test("no value is empty", () => {
    for (const locale of ["es", "en"] as const) {
      const empty = keys(CATALOGS[locale]).filter(
        (k) => translate(k, undefined, locale).trim() === "",
      );
      expect(empty).toEqual([]);
    }
  });

  test("every literal key used in the code exists in both languages", () => {
    const root = join(import.meta.dir, "..", "..");
    const missing: string[] = [];
    const call = /\bt\(\s*["'`]([a-zA-Z][\w-]*(?:\.[\w-]+)+)["'`]/g;
    for (const file of sourceFiles(root)) {
      const text = readFileSync(file, "utf8");
      for (const m of text.matchAll(call)) {
        const key = m[1] as string;
        const known = (k: string) =>
          es.has(k) || [...es].some((x) => PLURAL.test(x) && x.replace(PLURAL, "") === k);
        if (!known(key)) missing.push(`${file.replace(root, "src")}: ${key}`);
      }
    }
    expect(missing).toEqual([]);
  });
});

describe("translate", () => {
  test("Spanish and English", () => {
    expect(translate("nav.home", undefined, "es")).toBe("Inicio");
    expect(translate("nav.home", undefined, "en")).toBe("Home");
  });

  test("placeholders and plurals", () => {
    expect(translate("admin.users.count", { count: 1 }, "es")).toBe("1 cuenta");
    expect(translate("admin.users.count", { count: 3 }, "es")).toBe("3 cuentas");
    expect(translate("admin.users.count", { count: 1 }, "en")).toBe("1 account");
    expect(translate("common.updated", { when: "ahora" }, "es")).toBe("Actualizado ahora");
  });

  test("a leaf whose own name has dots (an audit action) is found", () => {
    expect(translate("profile.securityPanel.action.login.succeeded", undefined, "es")).toBe(
      "Inicio de sesión",
    );
    expect(translate("profile.securityPanel.action.mfa.enrolled", undefined, "en")).toBe(
      "Two-step verification turned on",
    );
    expect(hasKey("profile.securityPanel.action.not.an.action")).toBe(false);
  });

  test("a missing key falls back to the key itself, never throws", () => {
    setLocale("en");
    expect(translate("nope.not.here")).toBe("nope.not.here");
    expect(hasKey("nope.not.here")).toBe(false);
    setLocale("es");
  });
});
