/// <reference types="bun" />
/**
 * Plan PM, PM-14-10 (OP-50; FE-008): `robots.txt`, `llms.txt` and the pages' `noindex` say the same thing - the decision DM-12 of the
 * owner, «mantener cerrado». No page is indexed (every page carries noindex, so robots.txt must let a search engine read it), the API
 * is never crawled, AI crawlers read nothing but /llms.txt, and /llms.txt opens nothing. A change that contradicts one of the three
 * fails here; opening anything needs another decision of the owner (DM-12) and the legal consultation (DM-08).
 */
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const WEB = join(import.meta.dir, "..", "..", "..");
const read = (path: string) => readFileSync(join(WEB, path), "utf8");

const ROBOTS = read("public/robots.txt");
const LLMS = read("public/llms.txt");
const ROOT = read("src/routes/__root.tsx");
const OFFLINE = read("public/offline.html");

interface Group {
  agents: string[];
  rules: { allow: boolean; path: string }[];
}

/** robots.txt in groups (RFC 9309): consecutive User-agent lines open a group, the rules after them belong to it. */
function groups(text: string): Group[] {
  const out: Group[] = [];
  let current: Group | null = null;
  let inRules = false;
  for (const raw of text.split("\n")) {
    const line = raw.replace(/#.*$/, "").trim();
    if (!line) continue;
    const i = line.indexOf(":");
    if (i < 0) continue;
    const field = line.slice(0, i).trim().toLowerCase();
    const value = line.slice(i + 1).trim();
    if (field === "user-agent") {
      if (!current || inRules) {
        current = { agents: [], rules: [] };
        out.push(current);
        inRules = false;
      }
      current.agents.push(value.toLowerCase());
    } else if ((field === "allow" || field === "disallow") && current) {
      inRules = true;
      current.rules.push({ allow: field === "allow", path: value });
    }
  }
  return out;
}

/** Whether `agent` may fetch `path`: its own group (or `*`), the longest matching rule, Allow winning a tie (RFC 9309). */
function allowed(text: string, agent: string, path: string): boolean {
  const all = groups(text);
  const own = all.filter((g) => g.agents.includes(agent.toLowerCase()));
  const group = own.length ? own : all.filter((g) => g.agents.includes("*"));
  let best: { allow: boolean; path: string } | null = null;
  for (const g of group) {
    for (const r of g.rules) {
      if (!r.path || !path.startsWith(r.path)) continue;
      if (
        !best ||
        r.path.length > best.path.length ||
        (r.path.length === best.path.length && r.allow)
      )
        best = r;
    }
  }
  return best ? best.allow : true;
}

const AI_AGENTS = [
  "GPTBot",
  "ChatGPT-User",
  "OAI-SearchBot",
  "ClaudeBot",
  "Claude-User",
  "Claude-SearchBot",
  "anthropic-ai",
  "Google-Extended",
  "Applebot-Extended",
  "CCBot",
  "PerplexityBot",
  "Perplexity-User",
  "Bytespider",
  "Meta-ExternalAgent",
  "Amazonbot",
  "cohere-ai",
];

describe("no page is indexed", () => {
  test("every page carries noindex, nofollow from the root route", () => {
    expect(ROOT).toContain('{ name: "robots", content: "noindex, nofollow" }');
  });

  test("the offline page too", () => {
    expect(OFFLINE).toContain('<meta name="robots" content="noindex, nofollow">');
  });

  test("search engines may read the pages, so they see the noindex", () => {
    for (const agent of ["Googlebot", "Bingbot", "Twitterbot", "facebookexternalhit", "*"]) {
      for (const path of ["/", "/login", "/matches/1", "/help/how-it-works"]) {
        expect(`${agent} ${path} ${allowed(ROBOTS, agent, path)}`).toBe(`${agent} ${path} true`);
      }
    }
  });

  test("no sitemap: nothing is offered for indexing", () => {
    expect(ROBOTS).not.toMatch(/^\s*sitemap\s*:/im);
  });
});

describe("the API is never crawled", () => {
  test("nobody may fetch /api/ or /health", () => {
    for (const agent of ["Googlebot", "*", ...AI_AGENTS]) {
      for (const path of ["/api/v1/auth/me", "/api/v1/matches/1/forecast", "/health"]) {
        expect(`${agent} ${path} ${allowed(ROBOTS, agent, path)}`).toBe(`${agent} ${path} false`);
      }
    }
  });

  test("no rule anywhere allows the API", () => {
    expect(
      groups(ROBOTS)
        .flatMap((g) => g.rules)
        .filter((r) => r.allow && r.path.startsWith("/api")),
    ).toEqual([]);
  });
});

describe("AI crawlers read only /llms.txt", () => {
  test("every page is closed to them, /llms.txt is open", () => {
    for (const agent of AI_AGENTS) {
      expect(`${agent} ${allowed(ROBOTS, agent, "/")}`).toBe(`${agent} false`);
      expect(`${agent} ${allowed(ROBOTS, agent, "/matches/1")}`).toBe(`${agent} false`);
      expect(`${agent} ${allowed(ROBOTS, agent, "/llms.txt")}`).toBe(`${agent} true`);
    }
  });

  test("the parser reads groups as RFC 9309 does", () => {
    const text =
      "User-agent: a\nUser-agent: b\nDisallow: /\n\nUser-agent: *\nAllow: /\nDisallow: /x\n";
    expect(allowed(text, "b", "/y")).toBe(false);
    expect(allowed(text, "c", "/y")).toBe(true);
    expect(allowed(text, "c", "/x/1")).toBe(false);
  });
});

describe("/llms.txt opens nothing", () => {
  test("it says the service is private and offers no page, document or datum", () => {
    expect(LLMS.startsWith("# PrediGol\n")).toBe(true);
    expect(LLMS).toContain("servicio privado");
    expect(LLMS).toContain("No hay contenido público para asistentes de IA");
    expect(LLMS).toContain("La API (`/api/`) no se rastrea ni se usa");
  });

  test("no link and no path to read: no URL, no markdown link, no route but the API it closes", () => {
    expect(LLMS).not.toMatch(/https?:\/\//);
    expect(LLMS).not.toMatch(/\]\(/);
    const paths = [...LLMS.matchAll(/`(\/[^`]*)`/g)].map((m) => m[1]);
    expect(paths).toEqual(["/api/"]);
  });
});
