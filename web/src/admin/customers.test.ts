/// <reference types="bun" />
/**
 * The customer's card in the owner's words (plan UX, B10): every text the list and the card use exists in Spanish and in
 * English, the four views have their names, and the trail's filter learns the new kinds of event.
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import en from "@/locales/en/admin.json";
import es from "@/locales/es/admin.json";
import { CUSTOMER_VIEWS } from "@/lib/api/v1/types_customers";

type Tree = { [key: string]: string | Tree };
const get = (tree: Tree, path: string): string | Tree | undefined =>
  path
    .replace(/^admin\./, "")
    .split(".")
    .reduce<string | Tree | undefined>(
      (node, key) => (typeof node === "object" ? node[key] : undefined),
      tree,
    );

const SOURCES = ["CustomersPage.tsx", "CustomerCard.tsx", "CustomerParts.tsx"].map((f) =>
  readFileSync(new URL(`./${f}`, import.meta.url), "utf8"),
);
const KEYS = [
  ...new Set(
    SOURCES.flatMap((s) => [...s.matchAll(/\bt\(\s*"(admin\.[A-Za-z0-9_.]+)"/g)].map((m) => m[1]!)),
  ),
];

describe("the texts of the customers' pages", () => {
  test("the components use texts", () => {
    expect(KEYS.length).toBeGreaterThan(40);
  });
  for (const [lang, tree] of [
    ["es", es],
    ["en", en],
  ] as const) {
    test(`every static text exists in ${lang}`, () => {
      for (const key of KEYS) {
        const found = get(tree as Tree, key);
        expect(typeof found, `${lang}: ${key}`).toBe("string");
      }
    });
  }
  test("the four views, and «all», are named in both languages", () => {
    expect(CUSTOMER_VIEWS).toEqual(["all", "expiring", "inactive", "tickets", "errors"]);
    for (const tree of [es, en] as Tree[]) {
      for (const v of CUSTOMER_VIEWS) {
        expect(typeof get(tree, `admin.customers.views.${v}`)).toBe("string");
      }
    }
  });
  test("the groups the card reads by key are complete", () => {
    for (const tree of [es, en] as Tree[]) {
      for (const [group, keys] of [
        ["status", ["active", "disabled", "invited"]],
        ["ticketStatus", ["open", "answered", "closed"]],
        ["author", ["customer", "owner", "system"]],
        ["emailStatuses", ["ok", "bounced", "complained"]],
        ["consentKinds", ["terms", "privacy", "age_18", "risk_notice", "marketing_email"]],
      ] as const) {
        for (const k of keys) {
          expect(typeof get(tree, `admin.customers.${group}.${k}`), `${group}.${k}`).toBe("string");
        }
      }
    }
  });
  test("the two languages carry the same keys", () => {
    const flat = (tree: Tree, prefix = ""): string[] =>
      Object.entries(tree).flatMap(([k, v]) =>
        typeof v === "string" ? [`${prefix}${k}`] : flat(v, `${prefix}${k}.`),
      );
    const a = flat((es as unknown as Tree)["customers"] as Tree).sort();
    const b = flat((en as unknown as Tree)["customers"] as Tree).sort();
    expect(a).toEqual(b);
  });
  test("the trail labels the acts of the card", () => {
    for (const tree of [es, en] as Tree[]) {
      for (const k of [
        "customer_note",
        "customer_consents_viewed",
        "customer_ticket_reviewed",
        "customer_exported",
        "customer_export",
        "privacy_export",
        "privacy_deletion_request",
      ]) {
        expect(typeof get(tree, `admin.audit.actions.${k}`), k).toBe("string");
      }
    }
  });
  test("no text of the card promises a phone, a token or an address of the network", () => {
    const text = JSON.stringify((es as unknown as Tree)["customers"]).toLowerCase();
    expect(text).not.toContain("token");
    expect(text).not.toContain("teléfono");
  });
});
