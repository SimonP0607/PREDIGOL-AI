/// <reference types="bun" />
/**
 * PLAN F3, the decisions on a pair of referees: an open pair offers to keep either name (the busier first) or to call them two
 * men; a decided pair offers nothing to change but taking a rejection back. In both languages.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import type { PairStatus, RefereeSide } from "@/lib/api/v1/types_referees";
import { PairDecision } from "./RefereeDecisions";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");

const a: RefereeSide = { id: 1, name: "M. Oliver", country: "England", matches: 12 };
const b: RefereeSide = { id: 2, name: "Michael Oliver", country: "England", matches: 80 };

function render(status: PairStatus): string {
  return text(
    renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <PairDecision a={a} b={b} status={status} />
      </QueryClientProvider>,
    ),
  );
}

afterEach(() => setLocale("en"));

describe("PairDecision", () => {
  test("an open pair offers both names, the busier first, and the two-men answer", () => {
    setLocale("en");
    const out = render("open");
    expect(out.indexOf("keep Michael Oliver")).toBeGreaterThan(-1);
    expect(out.indexOf("keep Michael Oliver")).toBeLessThan(out.indexOf("keep M. Oliver"));
    expect(out).toContain("Two different people");
  });

  test("in Spanish too", () => {
    setLocale("es");
    const out = render("open");
    expect(out).toContain("conservar a Michael Oliver");
    expect(out).toContain("Son dos personas distintas");
  });

  test("a rejected pair can only go back to doubt; a merged one offers nothing", () => {
    setLocale("en");
    expect(render("rejected")).toContain("Back to doubt");
    expect(render("rejected")).not.toContain("keep ");
    const merged = render("merged");
    expect(merged).toContain("Merged");
    expect(merged).not.toContain("Back to doubt");
  });
});
