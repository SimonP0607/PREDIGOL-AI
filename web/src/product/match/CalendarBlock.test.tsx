/// <reference types="bun" />
/**
 * Plan F4, CALENDARIO Y DESCANSO in the Resumen: what each team played and has coming in every competition, how sure that is
 * ("Completo" / "Parcial", rest "como máximo" when the list is not whole), no price and no pick anywhere, and nothing at all for a
 * user until the owner decides. The Admin Console's preview sees every state.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import enMatch from "@/locales/en/match.json";
import esMatch from "@/locales/es/match.json";
import type { Envelope } from "@/lib/api/v1/types";
import type { CalendarMatch, MatchCalendar, TeamCalendar } from "@/lib/api/v1/types_calendar";
import { CalendarView } from "./CalendarBlock";
import {
  calendarScreen,
  daysText,
  distanceText,
  fortnightText,
  incompleteNote,
  kindLabel,
  matchTitle,
  opponentText,
  outsideText,
  restText,
  type CalendarLoad,
} from "./calendar";

setLocale("es");
afterEach(() => setLocale("es"));

const READ = "2026-10-22T09:00:00Z";
const KICKOFF = "2026-10-24T01:00:00Z";

function entry(over: Partial<CalendarMatch> = {}): CalendarMatch {
  return {
    provider_fixture_id: 9_100_001,
    kickoff_at: "2026-10-21T19:00:00Z",
    days: 2.3,
    competition: "Copa del Rey",
    competition_type: "domestic_cup",
    country: "Spain",
    round: "Round of 16",
    home: true,
    opponent: "Other FC",
    result: "2-1",
    followed: false,
    ...over,
  };
}

function side(over: Partial<TeamCalendar> = {}): TeamCalendar {
  return {
    team_id: 11,
    team: "Nashville SC",
    complete: true,
    reason: null,
    fetched_at: READ,
    age_hours: 20,
    rest_days: 2.3,
    matches_last_7d: 1,
    matches_last_14d: 3,
    matches_last_30d: 5,
    outside_last_14d: 1,
    recent: [
      entry(),
      entry({
        provider_fixture_id: 9_100_002,
        days: 8,
        competition: "Calendar League",
        competition_type: "domestic_league",
        round: null,
        opponent: "Rival FC",
        result: "1-0",
        home: false,
        followed: true,
      }),
    ],
    upcoming: [
      entry({
        provider_fixture_id: 9_100_003,
        days: 4,
        competition: "Champions League",
        competition_type: "continental",
        round: null,
        opponent: "Third FC",
        result: null,
        home: false,
      }),
    ],
    ...over,
  };
}

function calendar(home: TeamCalendar, away: TeamCalendar): MatchCalendar {
  const complete = home.complete && away.complete;
  return {
    fixture_id: 45140,
    kickoff_at: KICKOFF,
    status_group: "scheduled",
    complete,
    scope: complete ? "provider_calendar" : "tracked_competitions",
    home,
    away,
  };
}

function envelope(data: MatchCalendar | null, status: Envelope<unknown>["status"] = "ok") {
  return {
    status,
    data,
    reason: status === "ok" ? null : "The calendar of a match is not shown to users yet.",
    meta: {
      generated_at: READ,
      api_version: "v1",
      count: null,
      total: null,
      limit: null,
      offset: null,
      data_as_of: READ,
    },
  } as unknown as Envelope<MatchCalendar | null>;
}

function render(load: CalendarLoad, preview: boolean): string {
  return renderToStaticMarkup(<CalendarView load={load} preview={preview} />);
}

const whole = (): CalendarLoad => ({
  status: "success",
  envelope: envelope(calendar(side(), side({ team_id: 12, team: "Inter Miami", rest_days: 7 }))),
});

describe("what a user sees once the owner lets users see the calendar", () => {
  const out = render(whole(), false);

  test("the title, and the words that say it is context and not a recommendation", () => {
    expect(out).toContain('data-testid="calendar-block"');
    expect(out).toContain("Calendario y descanso");
    expect(out).toContain("en todas sus competiciones y no solo en la de este partido");
    expect(out).toContain("Es contexto, no una recomendación");
    expect(out).not.toContain('data-preview="true"');
  });

  test("both sides, each with its team and a «Completo» tag", () => {
    const sides = [
      ...out.matchAll(/data-testid="calendar-side" data-side="([^"]+)" data-complete="([^"]+)"/g),
    ];
    expect(sides.map((m) => [m[1], m[2]])).toEqual([
      ["home", "true"],
      ["away", "true"],
    ]);
    expect(out).toContain("Nashville SC");
    expect(out).toContain("Inter Miami");
    expect(out.match(/Completo/g)?.length).toBe(2);
    expect(out).not.toContain("Parcial");
  });

  test("the rest in days, exact, with the matches of the last fortnight and how many were elsewhere", () => {
    expect(out).toContain("2,3 días desde su último partido");
    expect(out).toContain("7 días desde su último partido");
    expect(out).toContain("3 partidos");
    expect(out).toContain("1 en una competición que PrediGol no sigue");
    expect(out).not.toContain("como máximo");
    expect(out).not.toContain("al menos");
  });

  test("the matches played: competition and round, how long before, the kind, the rival, where, and the score", () => {
    const recent = [...out.matchAll(/data-testid="calendar-recent" data-followed="([^"]+)"/g)].map(
      (m) => m[1],
    );
    expect(recent).toEqual(["false", "true", "false", "true"]);
    expect(out).toContain("Copa del Rey · Octavos de final");
    expect(out).not.toContain("Round of 16");
    expect(out).toContain("2,3 días antes");
    expect(out).toContain("8 días antes");
    expect(out).toContain("vs Other FC (local)");
    expect(out).toContain("vs Rival FC (visitante)");
    expect(out).toContain(">2-1<");
    expect(out).toContain(">1-0<");
    expect(out).toContain(">Copa<");
    expect(out).toContain(">Liga<");
  });

  test("the next match: competition, how long after, the rival, and no score", () => {
    expect(out).toContain("Champions League");
    expect(out).toContain("4 días después");
    expect(out).toContain("vs Third FC (visitante)");
    expect(out).toContain(">Continental<");
    const upcoming = [...out.matchAll(/<li data-testid="calendar-upcoming".*?<\/li>/g)].map(
      (m) => m[0],
    );
    expect(upcoming.length).toBe(2);
    for (const html of upcoming) expect(html).not.toContain('data-testid="calendar-result"');
  });

  test("across the width of «Profundizar»: a team in each column from a tablet up, each as tall as what it holds", () => {
    const grid = /<div class="([^"]*)" data-testid="calendar-sides">/.exec(out)?.[1] ?? "";
    expect(grid.split(" ")).toEqual(
      expect.arrayContaining(["grid", "items-start", "md:grid-cols-2"]),
    );
    // no longer stacked back into one column on a desktop, where it had a third of the row
    expect(grid).not.toContain("lg:grid-cols-1");
  });

  test("no price, no probability, no pick anywhere", () => {
    for (const word of ["cuota", "Cuota", "probabilidad", "apuesta", "Pick", "valor", "%"]) {
      expect(out).not.toContain(word);
    }
  });
});

describe("a side whose calendar is not whole says so", () => {
  const partial = side({
    team: "Nashville SC",
    complete: false,
    reason: "never_fetched",
    fetched_at: null,
    age_hours: null,
    rest_days: 8,
    matches_last_14d: 2,
    outside_last_14d: 0,
    recent: [entry({ days: 8, followed: true, competition: "Calendar League" })],
    upcoming: [],
  });
  const load: CalendarLoad = {
    status: "success",
    envelope: envelope(calendar(partial, side({ team: "Inter Miami" }))),
  };
  const out = render(load, false);

  test("«Parcial», the rest as a maximum and the matches as a minimum", () => {
    expect(out).toContain('data-side="home" data-complete="false"');
    expect(out).toContain("Parcial");
    expect(out).toContain("como máximo 8 días desde su último partido");
    expect(out).toContain("al menos 2 partidos");
  });

  test("a sentence names the team and why", () => {
    expect(out).toContain("PrediGol todavía no ha leído el calendario completo de Nashville SC");
    expect(out).toContain("Nada conocido en los 7 días siguientes.");
    expect(out).toContain("Cuando el calendario de un equipo no está completo");
  });

  test("the side that is whole is still said to be", () => {
    expect(out).toContain('data-side="away" data-complete="true"');
    expect(out.match(/data-testid="calendar-note"/g)?.length).toBe(1);
  });

  test("each reason has its own sentence, with the age in days for a list read too long ago", () => {
    const base = { team: "Nashville SC", complete: false } as const;
    expect(incompleteNote({ ...base, reason: "never_fetched", age_hours: null })).toContain(
      "todavía no ha leído",
    );
    expect(incompleteNote({ ...base, reason: "stale", age_hours: 144 })).toContain(
      "se leyó hace 6 días",
    );
    expect(incompleteNote({ ...base, reason: "unconfirmed_match", age_hours: 20 })).toContain(
      "Falta confirmar un partido reciente de Nashville SC",
    );
    expect(incompleteNote({ team: "X", complete: true, reason: null, age_hours: 5 })).toBe("");
  });

  test("a team with no earlier match says so instead of showing an empty list", () => {
    const none = side({ rest_days: null, recent: [], upcoming: [] });
    const html = render({ status: "success", envelope: envelope(calendar(none, side())) }, false);
    expect(html).toContain("Sin partido anterior conocido");
    expect(html).toContain("Ningún partido anterior conocido.");
    expect(html).toContain("Nada en los 7 días siguientes.");
  });
});

describe("a reader sees it load and fail; only the owner's switch hides it (plan UX, A9)", () => {
  test("the API says not available (the owner turned the calendar off for readers)", () => {
    const load: CalendarLoad = { status: "success", envelope: envelope(null, "not_available") };
    expect(render(load, false)).toBe("");
  });

  test("while it loads a skeleton, and when it cannot be loaded the error with its retry: never a silent gap", () => {
    expect(render({ status: "pending" }, false)).toContain("animate-pulse");
    const failed = render({ status: "error", error: new Error("boom") }, false);
    expect(failed).not.toBe("");
    expect(failed).toContain('role="alert"');
  });

  test("the screen is decided apart from React", () => {
    expect(calendarScreen({ status: "pending" }, false).kind).toBe("loading");
    expect(calendarScreen({ status: "pending" }, true).kind).toBe("loading");
    expect(calendarScreen({ status: "error", error: 1 }, false).kind).toBe("error");
    expect(calendarScreen({ status: "error", error: 1 }, true).kind).toBe("error");
    expect(calendarScreen(whole(), false).kind).toBe("calendar");
    const gone: CalendarLoad = { status: "success", envelope: envelope(null, "not_available") };
    expect(calendarScreen(gone, true).kind).toBe("none");
  });
});

describe("the Admin Console's preview", () => {
  test("is marked as a preview, and says so when the API has nothing", () => {
    const out = render(whole(), true);
    expect(out).toContain('data-preview="true"');
    expect(out).toContain("Modo de evaluación");
    const gone: CalendarLoad = { status: "success", envelope: envelope(null, "not_available") };
    const none = render(gone, true);
    expect(none).toContain('data-screen="none"');
    expect(none).toContain('data-testid="calendar-none"');
  });

  test("shows its own loading and error states", () => {
    expect(render({ status: "pending" }, true)).toContain('data-screen="loading"');
    const failed = render({ status: "error", error: new Error("boom") }, true);
    expect(failed).toContain('data-screen="error"');
    expect(failed).toContain('role="alert"');
  });
});

describe("in English", () => {
  test("the same block, in the reader's language", () => {
    setLocale("en");
    const out = render(whole(), false);
    expect(out).toContain("Schedule and rest");
    expect(out).toContain("2.3 days since its last match");
    expect(out).toContain("3 matches");
    expect(out).toContain("1 in a competition PrediGol does not follow");
    expect(out).toContain("2.3 days before");
    expect(out).toContain("4 days after");
    expect(out).toContain("vs Rival FC (away)");
    expect(out).toContain("Copa del Rey · Round of 16");
    expect(out).toContain("This is context, not a recommendation");
    expect(out).not.toContain("Calendario");
  });

  test("a partial side in English", () => {
    setLocale("en");
    const partial = side({ complete: false, reason: "stale", age_hours: 144, rest_days: 8 });
    const out = render({ status: "success", envelope: envelope(calendar(partial, side())) }, false);
    expect(out).toContain("Partial");
    expect(out).toContain("at most 8 days since its last match");
    expect(out).toContain("at least 3 matches");
    expect(out).toContain("The calendar of Nashville SC was read 6 days ago");
  });
});

describe("the words", () => {
  test("days: whole or with one decimal, singular and plural, in both languages", () => {
    expect(daysText(1)).toBe("1 día");
    expect(daysText(2)).toBe("2 días");
    expect(daysText(2.5)).toBe("2,5 días");
    setLocale("en");
    expect(daysText(1)).toBe("1 day");
    expect(daysText(2.5)).toBe("2.5 days");
  });

  test("how far from the match: before for a match played, after for one to come", () => {
    expect(distanceText({ days: 3 }, false)).toBe("3 días antes");
    expect(distanceText({ days: 1 }, false)).toBe("1 día antes");
    expect(distanceText({ days: 4 }, true)).toBe("4 días después");
    expect(distanceText({ days: 0.25 }, true)).toBe("0,3 días después");
  });

  test("rest: exact when whole, a maximum when not, and none when no match is known", () => {
    expect(restText({ rest_days: 3, complete: true })).toBe("3 días desde su último partido");
    expect(restText({ rest_days: 3, complete: false })).toBe(
      "como máximo 3 días desde su último partido",
    );
    expect(restText({ rest_days: null, complete: true })).toBe("Sin partido anterior conocido");
  });

  test("the fortnight: a count when whole, a minimum when not, and the outside part only when there is one", () => {
    expect(fortnightText({ matches_last_14d: 1, complete: true })).toBe("1 partido");
    expect(fortnightText({ matches_last_14d: 1, complete: false })).toBe("al menos 1 partido");
    expect(outsideText({ outside_last_14d: 0 })).toBe("");
    expect(outsideText({ outside_last_14d: 1 })).toBe("1 en una competición que PrediGol no sigue");
    expect(outsideText({ outside_last_14d: 2 })).toBe("2 en competiciones que PrediGol no sigue");
  });

  test("the kind of a competition is PrediGol's own; an unknown one has no label, not a key", () => {
    expect(kindLabel("domestic_cup")).toBe("Copa");
    expect(kindLabel("continental")).toBe("Continental");
    expect(kindLabel("international")).toBe("Selecciones");
    expect(kindLabel(null)).toBe("");
    expect(kindLabel("something_new")).toBe("");
  });

  test("the title carries the round when there is one, and the rival only when the provider named it", () => {
    expect(matchTitle({ competition: "Copa del Rey", round: "Final" })).toBe(
      "Copa del Rey · Final",
    );
    expect(matchTitle({ competition: "Copa del Rey", round: null })).toBe("Copa del Rey");
    expect(opponentText({ opponent: null, home: true })).toBe("");
    expect(opponentText({ opponent: "Other FC", home: false })).toBe("vs Other FC (visitante)");
  });
});

describe("the round, as the header names it (plan Partidos y Match Center, C2)", () => {
  const rounds = [
    { competition: "La Liga", round: "Regular Season - 11" },
    { competition: "Copa del Rey", round: "Round of 128" },
    { competition: "UEFA Champions League", round: "League Stage - 4" },
  ];

  test("in Spanish, never the provider's English", () => {
    expect(rounds.map(matchTitle)).toEqual([
      "La Liga · Jornada 11",
      "Copa del Rey · 1/64 de final",
      "UEFA Champions League · Fase liga · Jornada 4",
    ]);
    for (const title of rounds.map(matchTitle)) {
      expect(title).not.toMatch(/Regular Season|Round of|League Stage/);
    }
  });

  test("in English, in the reader's English", () => {
    setLocale("en");
    expect(rounds.map(matchTitle)).toEqual([
      "La Liga · Matchday 11",
      "Copa del Rey · Round of 128",
      "UEFA Champions League · League stage · Matchday 4",
    ]);
  });

  test("a round PrediGol does not know is kept as the provider wrote it, never dropped", () => {
    expect(matchTitle({ competition: "Copa", round: "Something New" })).toBe(
      "Copa · Something New",
    );
  });

  test("in the block itself", () => {
    const played = side({
      recent: [entry({ competition: "La Liga", round: "Regular Season - 11" })],
    });
    const out = render({ status: "success", envelope: envelope(calendar(played, side())) }, false);
    expect(out).toContain("La Liga · Jornada 11");
    expect(out).not.toContain("Regular Season");
  });
});

describe("the texts", () => {
  /** The pages are written in two languages: every key of the block exists in both, with the same placeholders. */
  function flatten(node: unknown, prefix = ""): Record<string, string> {
    if (typeof node === "string") return { [prefix]: node };
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      Object.assign(out, flatten(v, prefix ? `${prefix}.${k}` : k));
    }
    return out;
  }
  const es = flatten(esMatch.calendar);
  const en = flatten(enMatch.calendar);

  test("both languages have the same keys", () => {
    expect(Object.keys(en).sort()).toEqual(Object.keys(es).sort());
  });

  test("and the same placeholders in each", () => {
    const holes = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of Object.keys(es)) {
      expect({ key, holes: holes(en[key] as string) }).toEqual({
        key,
        holes: holes(es[key] as string),
      });
    }
  });

  test("the packet's «schedule» block has a label for the data the Resumen says it does not have", () => {
    const labelEs = (esMatch.analysis.block as Record<string, string>)["schedule"];
    const labelEn = (enMatch.analysis.block as Record<string, string>)["schedule"];
    expect(labelEs).toBe("calendario");
    expect(labelEn).toBe("schedule");
  });
});
