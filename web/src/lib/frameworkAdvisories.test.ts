/// <reference types="bun" />
/**
 * R02 of the security audit (24 Oct 2026), closed in phase A0 of the UX plan: the web framework is past the
 * advisories that were open on it.
 *
 *   @tanstack/react-start < 1.168.60, @tanstack/start-server-core < 1.169.39   GHSA-qx66-fv34-fjm8 (reflected XSS
 *     in server-function responses, unauthenticated)
 *   seroval <= 1.6.0 (GHSA-p6vx-979v-rg4c) and <= 1.6.2 (GHSA-jp82-f5mq-hwhp)    the serializer of the router
 *   zod < 4.6.6 (GHSA-mrhx-c7xc-m3w5)                                            pulled in by the router's build tools
 *
 * Read from bun.lock, which is exactly what the image installs (`bun install --frozen-lockfile`): every copy the
 * lock resolves - a nested one included - must be at least the fixed version, so an update that brings an old copy
 * back fails here, before anything is built or deployed.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const LOCK = readFileSync(join(import.meta.dir, "..", "..", "bun.lock"), "utf8");

/** [package, the first fixed version, the advisories it closes] */
const FLOORS: ReadonlyArray<readonly [string, string, string]> = [
  ["@tanstack/react-start", "1.168.60", "GHSA-qx66-fv34-fjm8"],
  ["@tanstack/start-server-core", "1.169.39", "GHSA-qx66-fv34-fjm8"],
  ["seroval", "1.6.3", "GHSA-p6vx-979v-rg4c, GHSA-jp82-f5mq-hwhp"],
  ["zod", "4.6.6", "GHSA-mrhx-c7xc-m3w5"],
];

/** Every version of `name` the lock resolves: its own entry and every nested copy ("parent/name"). */
export function resolved(lock: string, name: string): string[] {
  const versions: string[] = [];
  for (const m of lock.matchAll(/^\s*"([^"]+)": \["(@?[^@"]+)@([^"]+)"/gm)) {
    const [, key = "", pkg = "", version = ""] = m;
    if (pkg === name && (key === name || key.endsWith(`/${name}`))) versions.push(version);
  }
  return versions;
}

/** version >= floor, by major.minor.patch; a pre-release of the floor itself is below it. */
export function atLeast(version: string, floor: string): boolean {
  const [core = "", pre] = version.split(/-(.*)/s);
  const a = core.split("+")[0]?.split(".").map(Number) ?? [];
  const b = floor.split(".").map(Number);
  for (let i = 0; i < 3; i++) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x !== y) return x > y;
  }
  return pre === undefined;
}

describe("R02: the web framework is past the advisories open on it", () => {
  for (const [name, floor, advisories] of FLOORS) {
    test(`every copy of ${name} in bun.lock is ${floor} or later (${advisories})`, () => {
      const versions = resolved(LOCK, name);
      // Not found would pass vacuously: the package is really there, the parser read it.
      expect(versions.length).toBeGreaterThan(0);
      expect(versions.filter((v) => !atLeast(v, floor))).toEqual([]);
    });
  }
});

describe("the reading of the lock", () => {
  const SAMPLE = [
    `    "zod": ["zod@4.6.6", "", {}, "sha512-x"],`,
    `    "@tanstack/router-plugin/zod": ["zod@4.4.3", "", {}, "sha512-y"],`,
    `    "@tanstack/react-start": ["@tanstack/react-start@1.168.61", "", {}, "sha512-z"],`,
    `    "h3-v2": ["h3@2.0.1-rc.20", "", {}, "sha512-w"],`,
    `        "zod": "^4.6.6",`,
  ].join("\n");

  test("a nested copy is found as well as the package's own entry; a workspace range is not an entry", () => {
    expect(resolved(SAMPLE, "zod")).toEqual(["4.6.6", "4.4.3"]);
    expect(resolved(SAMPLE, "@tanstack/react-start")).toEqual(["1.168.61"]);
    expect(resolved(SAMPLE, "h3")).toEqual([]);
  });

  test("versions compare by number, and a pre-release of the floor is below it", () => {
    expect(atLeast("1.169.40", "1.169.39")).toBe(true);
    expect(atLeast("1.169.39", "1.169.39")).toBe(true);
    expect(atLeast("1.169.38", "1.169.39")).toBe(false);
    expect(atLeast("1.170.0", "1.169.39")).toBe(true);
    expect(atLeast("1.6.10", "1.6.3")).toBe(true);
    expect(atLeast("3.25.76", "4.6.6")).toBe(false);
    expect(atLeast("1.169.39-rc.1", "1.169.39")).toBe(false);
    expect(atLeast("1.169.40-rc.1", "1.169.39")).toBe(true);
  });
});
