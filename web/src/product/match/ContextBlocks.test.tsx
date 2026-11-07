/// <reference types="bun" />
/**
 * Mobile UX audit (October 2026), the Match Center's summary at 320 px: a team's name beside its five form chips
 * and in the two-row standings table was cut ("Zorya Luh…"). Both now wrap.
 *
 * Plan F2: the full table that opens under the two rows names its columns, as the two-row table does.
 */
import { describe, expect, test } from "bun:test";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { setLocale } from "@/lib/i18n";
import type { H2HMatch, StandingLine, TableRow } from "@/lib/api/v1/types_center";
import type { MatchCtx } from "./context";
import {
  AbsencesBlock,
  FormBlock,
  FullTable,
  H2HBlock,
  LineupsTeaser,
  StandingsBlock,
} from "./ContextBlocks";
import { DeepenLayout } from "./SummaryTab";

setLocale("es");

async function html(node: ReactNode): Promise<string> {
  const router = createRouter({
    routeTree: createRootRoute({ component: () => node }),
    history: createMemoryHistory({ initialEntries: ["/"] }),
  });
  await router.load();
  return renderToStaticMarkup(<RouterProvider router={router} />);
}

function line(side: "home" | "away", team: string, rank: number): StandingLine {
  return {
    side,
    team,
    rank,
    points: 20 - rank,
    played: 9,
    wins: 5,
    draws: 2,
    losses: 2,
    goals_for: 14,
    goals_against: 9,
    form: "WWDLW",
    group: null,
    snapshot_at: "2026-10-12T04:00:00Z",
    before_kickoff: true,
  };
}

// Only what the two blocks read: the teams, and the stored standings (their form letters feed the chips).
const ctx = {
  fixtureId: "21676",
  match: {
    id: 21676,
    home: { id: 1, name: "Livyi Bereh", logo_url: null },
    away: { id: 2, name: "Zorya Luhansk", logo_url: null },
    competition: { id: 177, name: "Premier League" },
  },
  center: {
    data: {
      form: { status: "empty", data: [], reason: null },
      standings: {
        status: "ok",
        data: [line("home", "Livyi Bereh", 7), line("away", "Zorya Luhansk", 3)],
        reason: null,
      },
      standings_tables: [],
    },
    loading: false,
    error: null,
    status: null,
    retry: () => {},
  },
  showAdmin: false,
  goTo: () => {},
} as unknown as MatchCtx;

function nameTags(out: string): string[] {
  return [...out.matchAll(/<span[^>]*data-testid="team-name"[^>]*>/g)].map((m) => m[0]);
}

describe("the Match Center's context blocks keep team names whole", () => {
  test("form: the name beside the five chips wraps", async () => {
    const out = await html(<FormBlock ctx={ctx} />);
    expect(out).toContain("Zorya Luhansk");
    const tags = nameTags(out);
    expect(tags.length).toBe(2);
    for (const tag of tags) expect(tag).not.toContain("truncate");
  });

  test("standings: the names in the fixed table wrap", async () => {
    const out = await html(<StandingsBlock ctx={ctx} />);
    expect(out).toContain("Livyi Bereh");
    const tags = nameTags(out);
    expect(tags.length).toBe(2);
    for (const tag of tags) expect(tag).not.toContain("truncate");
  });
});

function tableRow(rank: number, teamId: number, team: string): TableRow {
  return {
    rank,
    team_id: teamId,
    team,
    played: 9,
    wins: 5,
    draws: 2,
    losses: 2,
    goals_for: 14,
    goals_against: 9,
    points: 20 - rank,
    form: null,
    group: "Clausura",
  };
}

describe("the full table names its columns", () => {
  const rows = [
    tableRow(1, 10, "Atlas"),
    tableRow(2, 1, "Livyi Bereh"),
    tableRow(3, 11, "Boca"),
    tableRow(4, 2, "Zorya Luhansk"),
  ];

  test("one header row, a column header for each figure, and the table named", async () => {
    const out = await html(<FullTable rows={rows} mine={new Set([1, 2])} label="Clausura" />);

    expect(out).toContain("<thead>");
    expect(out.match(/<th scope="col"/g)?.length).toBe(5);
    for (const name of ["#", "Equipo", "PJ", "DG", "Pts"]) expect(out).toContain(`>${name}<`);
    // the long name opens on a tap and is read after the short one: it is no native title, which a phone never shows
    expect(out).toContain(": Partidos jugados</span>");
    expect(out).not.toContain("title=");
    expect(out).toContain('<caption class="sr-only">Clausura</caption>');
  });

  test("the header comes before the teams, and the two teams of the match are highlighted", async () => {
    const out = await html(<FullTable rows={rows} mine={new Set([1, 2])} label="Clausura" />);

    const head = out.indexOf("<thead>");
    expect(head).toBeGreaterThanOrEqual(0);
    expect(head).toBeLessThan(out.indexOf("Atlas"));
    expect(out.match(/bg-primary\/8/g)?.length).toBe(2);
  });

  test("in English the same columns", async () => {
    setLocale("en");
    try {
      const out = await html(<FullTable rows={rows} mine={new Set()} label="Clausura" />);

      for (const name of ["#", "Team", "P", "GD", "Pts"]) expect(out).toContain(`>${name}<`);
    } finally {
      setLocale("es");
    }
  });
});

/** One meeting of the two teams, a draw. */
function meeting(): H2HMatch {
  return {
    fixture_id: 9001,
    kickoff_at: "2025-04-12T15:00:00Z",
    competition: "Premier League",
    home: "Livyi Bereh",
    away: "Zorya Luhansk",
    goals_home: 1,
    goals_away: 1,
    regulation_goals_home: 1,
    regulation_goals_away: 1,
    after_extra_time: false,
    penalties_home: null,
    penalties_away: null,
    scope: "same_competition",
    home_side_was: "home",
  } as H2HMatch;
}

describe("«Profundizar» opened, with its own blocks (plan Partidos y Match Center, D1)", () => {
  const full = {
    ...ctx,
    center: {
      ...ctx.center,
      data: {
        ...ctx.center.data,
        h2h: { status: "ok", data: [meeting()], reason: null },
        absences: { status: "empty", data: [], reason: null },
        lineups: { status: "empty", data: [], reason: null },
      },
    },
  } as unknown as MatchCtx;

  async function opened(): Promise<string> {
    return html(
      <DeepenLayout
        blocks={{
          form: <FormBlock ctx={full} />,
          table: <StandingsBlock ctx={full} />,
          h2h: <H2HBlock ctx={full} />,
          calendar: <section data-testid="calendar-stub" />,
          absences: <AbsencesBlock ctx={full} />,
          lineups: <LineupsTeaser ctx={full} />,
        }}
      />,
    );
  }

  test("the same blocks, in reading order: form, table, head to head, calendar, absences, line-ups", async () => {
    const out = await opened();
    const at = [
      "Forma reciente",
      "Tabla de posiciones",
      "Enfrentamientos directos",
      "calendar-stub",
      "Bajas",
      "Alineaciones",
    ].map((x) => out.indexOf(x));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
  });

  test("each block's card may shrink to its column (min-w-0), and the names in it still wrap", async () => {
    const out = await opened();
    const cards = [...out.matchAll(/<div class="min-w-0[^"]*"><section class="([^"]*)"/g)].map(
      (m) => m[1] ?? "",
    );
    expect(cards.length).toBe(5);
    for (const cls of cards) expect(cls.split(" ")).toContain("min-w-0");
    expect(out).toContain("Zorya Luhansk");
  });

  test("one meeting is «1 partido», never «1 partidos»", async () => {
    const out = await opened();
    expect(out).toContain(">1 partido<");
    expect(out).not.toContain("1 partidos");
  });
});
