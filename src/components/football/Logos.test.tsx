/// <reference types="bun" />
/**
 * Mobile UX audit (October 2026): a match in a card is home above away with every name whole - one line
 * ("Gainare Tot… 0–1 FC Gifu") cut names even at desktop widths - and the goals of each side on its own line.
 */
import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import { CompetitionTag, Matchup, TeamName } from "./Logos";

setLocale("es");
const home = { name: "Borussia Mönchengladbach", logo: null };
const away = { name: "Deportivo Independiente Medellín", logo: null };

function names(html: string): string[] {
  return [...html.matchAll(/data-testid="team-name"[^>]*>([^<]+)</g)].map((m) => m[1] ?? "");
}

describe("Matchup", () => {
  test("home above away, each name whole: it wraps, it is never truncated", () => {
    const html = renderToStaticMarkup(<Matchup home={home} away={away} />);
    expect(names(html)).toEqual([home.name, away.name]);
    expect(html).not.toContain("truncate");
    expect(html).toContain("break-words");
  });

  test("the goals of each side on its own line, the losing side muted", () => {
    const html = renderToStaticMarkup(
      <Matchup home={home} away={away} score={{ home: 0, away: 3 }} />,
    );
    const goals = [...html.matchAll(/numeric[^"]*"[^>]*>(\d+)</g)].map((m) => m[1]);
    expect(goals).toEqual(["0", "3"]);
    expect(html).toMatch(/text-muted-foreground[^"]*"[^>]*>0</);
  });

  test("before kick-off there is no score and no 'vs' to squeeze the names", () => {
    const html = renderToStaticMarkup(<Matchup home={home} away={away} />);
    expect(html).not.toContain("numeric");
    expect(html).not.toContain(" vs ");
  });

  test("in play the goals take the live colour", () => {
    const html = renderToStaticMarkup(
      <Matchup home={home} away={away} score={{ home: 1, away: 1 }} live />,
    );
    expect((html.match(/text-primary/g) ?? []).length).toBe(2);
  });
});

describe("TeamName and CompetitionTag", () => {
  test("TeamName truncates by default (dense lists) and wraps on request (cards)", () => {
    expect(renderToStaticMarkup(<TeamName name={home.name} logo={null} />)).toContain("truncate");
    const wrapped = renderToStaticMarkup(<TeamName name={home.name} logo={null} wrap />);
    expect(wrapped).not.toContain("truncate");
    expect(wrapped).toContain(home.name);
  });

  test("a competition's name is whole ('UEFA Champions Le…' at 320 px was not)", () => {
    const html = renderToStaticMarkup(<CompetitionTag name="AFC Champions League Elite" />);
    expect(html).toContain("AFC Champions League Elite");
    expect(html).not.toContain("truncate");
  });
});
