/// <reference types="bun" />
/**
 * Plan F7, POSTPARTIDO in the Resumen of a finished match: what happened, as facts - how the score went, what the market
 * expected against what happened, the best of the match, the formations and the changes, and how far it can be trusted.
 * No pick, no forecast and no price for a user; nothing at all for a user until the owner decides; and the row as PrediGol
 * stores it (the decision layer's picks and the post-mortems among its nine layers) only in the Admin Console's preview.
 */
import { afterEach, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale } from "@/lib/i18n";
import enMatch from "@/locales/en/match.json";
import esMatch from "@/locales/es/match.json";
import type { Envelope } from "@/lib/api/v1/types";
import type {
  AfterMatch,
  KnowledgeEventLine,
  KnowledgeLayer,
  KnowledgeMarketBlock,
  KnowledgePeriod,
  KnowledgeEvents,
  KnowledgePlayers,
  KnowledgePlayersSide,
  KnowledgeResult,
  KnowledgeSide,
  KnowledgeStoredBuild,
  KnowledgeStory,
  KnowledgeTactics,
  KnowledgeTeamStats,
  MatchKnowledge,
} from "@/lib/api/v1/types_knowledge";
import { KnowledgeView } from "./KnowledgeBlock";
import {
  beforeKickoff,
  bestPlayers,
  cameIn,
  comebackOf,
  completenessLabel,
  completenessNote,
  doubtTexts,
  finalReads,
  headlines,
  knowledgeScreen,
  leadMinutes,
  leadText,
  leadTimeline,
  lineups,
  marketReads,
  noKnowledgeText,
  playerFigures,
  shortHash,
  storedLayers,
  storyDrawing,
  storyFacts,
  trackPercent,
  type KnowledgeLoad,
} from "./knowledge";
import { hasPlayerPage } from "./people";

setLocale("es");
afterEach(() => setLocale("es"));

const KNOWN = "2026-10-23T09:00:00Z";
const HOME = "Nashville SC";
const AWAY = "Inter Miami";
const SIDES = { home: HOME, away: AWAY };

// ── a finished match, as the API lays it out ────────────────────────────────

function layer<D>(
  data: D,
  status: KnowledgeLayer<D>["status"] = "ok",
  notes: string[] = [],
): KnowledgeLayer<D> {
  return { status, known_at: KNOWN, notes, data };
}

function missing<D>(notes: string[] = []): KnowledgeLayer<D> {
  return { status: "missing", known_at: null, notes, data: null };
}

function goal(
  minute: number,
  side: KnowledgeSide,
  period: KnowledgePeriod = minute <= 45 ? "1H" : "2H",
  kind = "goal",
): KnowledgeEventLine {
  return {
    seq: minute,
    kind,
    period,
    minute,
    extra: null,
    side,
    player_side: null,
    player: side === "home" ? 501 : 602,
    name: side === "home" ? "Man 501" : "Man 602",
    assist: null,
    assist_name: null,
    pair: null,
    flags: [],
  };
}

function result(over: Partial<KnowledgeResult> = {}): KnowledgeResult {
  return {
    match_status: "FT",
    kickoff: "2026-10-22T01:00:00Z",
    reg: [2, 1],
    outcome: "Home",
    total: 3,
    btts: true,
    decided_by: "regulation",
    ht: [1, 0],
    final: null,
    pen: null,
    neutral: false,
    corrected: false,
    tie: null,
    ...over,
  };
}

/** Home 12', away 70' (a penalty), home 85': the home side leads from the 12th to the 70th minute and again from the 85th. */
const GOALS = [goal(12, "home"), goal(70, "away", "2H", "penalty_goal"), goal(85, "home")];

const STORY: KnowledgeStory = {
  ahead: { home: true, away: false },
  lead_changes: 0,
  minutes: { home_ahead: 63, level: 27, away_ahead: 0 },
  first_goal: { minute: 12, side: "home" },
  last_goal_minute: 85,
  first_dismissal: { minute: 60, side: "away", lead: -1 },
};

const HOME_SIDE: KnowledgePlayersSide = {
  listed: 12,
  played: 12,
  started: 11,
  came_on: 1,
  top: [
    { player_id: 505, name: "Man 505", rating: 8.4, minutes: 90, goals: 1, assists: 0 },
    { player_id: 501, name: "Man 501", rating: 8.1, minutes: 90, goals: 1, assists: 1 },
    { player_id: 504, name: null, rating: 6.9, minutes: 74, goals: 0, assists: 0 },
  ],
  captain_id: 501,
};

const AWAY_SIDE: KnowledgePlayersSide = {
  listed: 12,
  played: 12,
  started: 11,
  came_on: 1,
  top: [{ player_id: 602, name: "Man 602", rating: 7.2, minutes: 90, goals: 1, assists: 0 }],
  captain_id: null,
};

const PLAYERS: KnowledgePlayers = { home: HOME_SIDE, away: AWAY_SIDE, goals_with_no_player: 0 };

const TACTICS: KnowledgeTactics = {
  home: {
    formation: "4-3-3",
    substitutions: [
      { minute: 58, lead: 1 },
      { minute: 70, lead: 0 },
    ],
  },
  away: { formation: "4-4-2", substitutions: [{ minute: 46, lead: -1 }] },
  story: STORY,
};

function market(
  probabilities: KnowledgeMarketBlock["probabilities"],
  over: Partial<KnowledgeMarketBlock> = {},
): KnowledgeMarketBlock {
  return {
    probabilities,
    books: 14,
    opened_at: "2026-10-16T12:00:00Z",
    closed_at: "2026-10-22T22:05:00Z",
    minutes_to_kickoff: 175,
    line: null,
    final: null,
    ...over,
  };
}

/** Kept out of the board's order on purpose: the page puts them in order. */
function markets(): Record<string, KnowledgeMarketBlock> {
  return {
    AH: market({ Home: [0.5, 0.51], Away: [0.5, 0.49] }, { line: -0.5 }),
    BTTS: market({ Yes: [null, 0.55], No: [null, 0.45] }),
    OU: market({ Over: [0.5, 0.57], Under: [0.5, 0.43] }, { line: 2.5 }),
    "1X2": market(
      { Home: [0.48, 0.52], Draw: [0.27, 0.26], Away: [0.25, 0.22] },
      {
        final: {
          odds: { Home: 1.85, Draw: 3.6, Away: 4.2 },
          books: 14,
          at: "2026-10-22T23:35:00Z",
          minutes_to_kickoff: 85,
        },
      },
    ),
  };
}

function golden(): AfterMatch {
  return {
    version: "mk-v1",
    completeness: "complete",
    built_at: KNOWN,
    known_at: KNOWN,
    quality: { events_give_the_score: true, doubts: [] },
    result: layer(result()),
    team_stats: layer<KnowledgeTeamStats>({ home: null, away: null }),
    events: layer<KnowledgeEvents>({
      rules: "events-v1",
      n: 8,
      counts: { goal: 2, penalty_goal: 1 },
      by_period: { "1H": [1, 0], "2H": [1, 1] },
      check: { reg: true, ht: true, et: null, pen: null, cards: true, listed: null },
      goals: GOALS,
      missed: [],
      shootout: [],
      cards: [],
      var: [],
    }),
    players: layer(PLAYERS),
    tactics: layer(TACTICS),
    market: layer({ markets: markets() }),
  };
}

const STORED: KnowledgeStoredBuild = {
  id: 12,
  supersedes: 7,
  inputs_hash: "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",
  content_hash: "0f9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6",
  layers: {
    c1_result: { status: "ok", known_at: KNOWN, sources: ["core.fixtures"], data: { reg: [2, 1] } },
    c2_team_stats: { status: "ok", known_at: KNOWN, data: { home: { shots: 14 } } },
    c3_events: { status: "ok", known_at: KNOWN, data: { n: 8 } },
    c4_players: { status: "ok", known_at: KNOWN, data: {} },
    c5_tactics: { status: "ok", known_at: KNOWN, data: {} },
    c6_market: { status: "partial", known_at: KNOWN, notes: ["no_BTTS"], data: {} },
    c7_context: { status: "off", notes: ["decided_by_the_owner"] },
    c8_picks: {
      status: "ok",
      known_at: KNOWN,
      data: { decisions: { n: 3, lines: 2 }, picks: { n: 1, by_market: { OU: { n: 1, win: 1 } } } },
    },
    c9_postmortem: {
      status: "ok",
      known_at: KNOWN,
      data: { n: 1, verdicts: { sound_process_bad_luck: 1 } },
    },
  },
  quality: {},
  chain: [
    {
      id: 7,
      supersedes: null,
      built_at: "2026-10-22T04:00:00Z",
      known_at: "2026-10-22T03:00:00Z",
      completeness: "partial",
      content_hash: "7777777777777777777777777777777777777777",
    },
    {
      id: 12,
      supersedes: 7,
      built_at: KNOWN,
      known_at: KNOWN,
      completeness: "complete",
      content_hash: "0f9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6",
    },
  ],
};

function knowledge(
  after: AfterMatch | null,
  over: Partial<MatchKnowledge> = {},
  code = "no_build_yet",
): MatchKnowledge {
  return {
    fixture_id: 45140,
    kickoff_at: "2026-10-22T01:00:00Z",
    status_group: "finished",
    knowledge: after
      ? { status: "ok", data: after, reason: null }
      : { status: "not_available", data: null, reason: "x", code },
    stored: null,
    ...over,
  };
}

function envelope(data: MatchKnowledge | null, status: Envelope<unknown>["status"] = "ok") {
  return {
    status,
    data,
    reason: status === "ok" ? null : "The after-match summary is not shown to users yet.",
    meta: {
      generated_at: KNOWN,
      api_version: "v1",
      count: null,
      total: null,
      limit: null,
      offset: null,
      data_as_of: KNOWN,
    },
  } as unknown as Envelope<MatchKnowledge | null>;
}

function loaded(after: AfterMatch | null, over: Partial<MatchKnowledge> = {}, code?: string) {
  return { status: "success", envelope: envelope(knowledge(after, over, code)) } as KnowledgeLoad;
}

function render(load: KnowledgeLoad, preview: boolean, admin = false): string {
  return renderToStaticMarkup(
    <KnowledgeView load={load} home={HOME} away={AWAY} preview={preview} admin={admin} />,
  );
}

/** The words on the page: no tags, the entities decoded, the spaces collapsed. */
function plain(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

// ── a user ──────────────────────────────────────────────────────────────────

describe("what a user sees once the owner lets users see the summary", () => {
  const html = render(loaded(golden()), false);
  const words = plain(html);

  test("the title, and the words that say it is facts and not a recommendation", () => {
    expect(html).toContain('data-testid="knowledge-block"');
    expect(html).toContain('data-screen="knowledge"');
    expect(html).toContain('data-preview="false"');
    expect(words).toContain("Postpartido");
    expect(words).toContain("Son hechos, no una recomendación");
  });

  test("the parts come in order: the story, the market, the best of the match, the formations, the trust", () => {
    const order = [
      "knowledge-story",
      "knowledge-markets",
      "knowledge-players",
      "knowledge-lineups",
      "knowledge-quality",
    ].map((id) => html.indexOf(`data-testid="${id}"`));
    expect(order.every((at) => at >= 0)).toBe(true);
    expect([...order].sort((a, b) => a - b)).toEqual(order);
  });

  test("the story: who led, in the order it happened, drawn where the numbers say", () => {
    expect(html).toContain('data-kind="timeline"');
    const level = trackPercent(12);
    expect(level).toBe(13.33);
    expect(html).toContain(`left:0%;width:${level}%`);
    expect(html).toContain(
      `left:13.33%;width:${Math.round((trackPercent(70) - 13.33) * 100) / 100}%`,
    );
    const segments = [
      ...html.matchAll(/<span data-state="(home|level|away)" class="absolute/g),
    ].map((m) => m[1]);
    expect(segments).toEqual(["level", "home", "level", "home"]);
    // the three goals are marked where they were scored
    const ticks = [
      ...html.matchAll(
        /data-testid="knowledge-goal" data-side="(home|away)"[^>]*style="left:([\d.]+)%"/g,
      ),
    ].map((m) => [m[1], m[2]]);
    expect(ticks).toEqual([
      ["home", "13.33"],
      ["away", "77.78"],
      ["home", "94.44"],
    ]);
  });

  test("the key under the bar says who led for how long, and leaves out who never did", () => {
    expect(words).toContain("Nashville SC por delante 63 min");
    expect(words).toContain("Empatados 27 min");
    expect(words).not.toContain("Inter Miami por delante");
    expect(html).toMatch(/role="img" aria-label="Quién iba por delante durante los 90 minutos: /);
  });

  test("the facts under the bar: first and last goal, lead changes, first man sent off with the score at the time", () => {
    expect(words).toContain("Primer gol Nashville SC, 12'");
    expect(words).toContain("Último gol 85'");
    expect(words).toContain("Cambios de ventaja 0");
    expect(words).toContain("Primera expulsión Inter Miami, 60' (perdiendo por 1)");
  });

  test("the market: the three core markets in the board's order, a handicap left to the Markets tab", () => {
    const keys = [...html.matchAll(/data-testid="knowledge-market" data-market="([^"]+)"/g)].map(
      (m) => m[1],
    );
    expect(keys).toEqual(["1X2", "OU", "BTTS"]);
    expect(words).toContain("Resultado final (1X2)");
    expect(words).toContain("Goles: más/menos de 2,5");
    expect(words).toContain("Ambos marcan");
    expect(html).not.toContain('data-market="AH"');
  });

  test("the market: closing probabilities as whole percentages, where each opened, and what happened marked", () => {
    expect(words).toMatch(/Gana Nashville SC .*?52\s%/);
    expect(words).toMatch(/abrió en 48\s%/);
    expect(words).toMatch(/Más de 2,5 .*?57\s%/);
    expect(words).not.toMatch(/52,\d\s%/);
    const rows = [
      ...html.matchAll(
        /data-testid="knowledge-selection" data-selection="([^"]+)" data-happened="(true|false)"/g,
      ),
    ].map((m) => `${m[1]}:${m[2]}`);
    expect(rows).toEqual([
      "Home:true",
      "Draw:false",
      "Away:false",
      "Over:true",
      "Under:false",
      "Yes:true",
      "No:false",
    ]);
    expect(words.match(/Ocurrió/g)?.length).toBe(3);
  });

  test("the market: what the market gave to what happened, and when it was last read", () => {
    expect(words).toMatch(
      /Al cierre, el mercado daba un 52\s% a lo que ocurrió \(había abierto en 48\s%\)\./,
    );
    expect(words).toMatch(/Al cierre, el mercado daba un 55\s% a lo que ocurrió\./);
    expect(words).toContain("sin lectura de apertura");
    expect(words).toContain("Lectura de cierre: 2 h 55 min antes del inicio, de 14 casas.");
  });

  test("the best of the match: three at most for each side, the best of both marked, a nameless man named as such", () => {
    const rows = [...html.matchAll(/data-testid="knowledge-player" data-best="(true|false)"/g)].map(
      (m) => m[1],
    );
    expect(rows).toEqual(["true", "false", "false", "false"]);
    expect(words).toContain("Man 505");
    expect(words).toContain("Jugador no informado por el proveedor");
    expect(words).toContain("90 min · 1 gol · 1 asistencia");
    expect(words).toContain("8,4");
  });

  test("the formations and the changes, with the lead of the side when each was made", () => {
    expect(words).toContain("Formación 4-3-3");
    expect(words).toContain("Formación 4-4-2");
    expect(words).toContain("2 cambios");
    expect(words).toContain("58' (ganando por 1)");
    expect(words).toContain("70' (empatando)");
    expect(words).toContain("46' (perdiendo por 1)");
  });

  test("how far it can be trusted: complete, with nothing to doubt", () => {
    expect(html).toContain('data-completeness="complete"');
    expect(words).toContain("Completo");
    expect(words).toContain("todos con datos fiables");
    expect(html).not.toContain("knowledge-doubts");
    expect(words).toContain("Actualizado");
  });

  test("no price, no pick, no recommendation and nothing of the row as stored", () => {
    for (const hidden of [
      "knowledge-admin",
      "knowledge-finals",
      "knowledge-stored-layer",
      "knowledge-chain",
      "c8_picks",
      "c9_postmortem",
      "Últimos precios",
      "1,85",
      "3,60",
      "Modo de evaluación",
    ]) {
      expect(html).not.toContain(hidden);
    }
  });

  test("a user is shown nothing of the row as stored even if the payload carried it", () => {
    // Defence in depth: the API sends it to the preview alone; the view shows it to the preview alone.
    const leaky = render(loaded(golden(), { stored: STORED }), false);
    for (const hidden of [
      "knowledge-admin",
      "c8_picks",
      "sound_process_bad_luck",
      "0f9e8d7c6b5a",
    ]) {
      expect(leaky).not.toContain(hidden);
    }
    expect(leaky).toBe(html);
  });
});

// ── nothing until the owner decides ─────────────────────────────────────────

describe("a reader sees it load and fail; only the owner's switch hides it (plan UX, A9)", () => {
  test("the API says not available (the owner turned the summary off for readers)", () => {
    const load = { status: "success", envelope: envelope(null, "not_available") } as KnowledgeLoad;
    expect(render(load, false)).toBe("");
  });

  test("while it loads a skeleton, and when it cannot be loaded the error with its retry: never a silent gap", () => {
    expect(render({ status: "pending" }, false)).toContain("animate-pulse");
    const failed = render({ status: "error", error: new Error("boom") }, false);
    expect(failed).not.toBe("");
    expect(failed).toContain('role="alert"');
  });

  test("the screen is decided apart from React", () => {
    expect(knowledgeScreen({ status: "pending" }, false).kind).toBe("loading");
    expect(knowledgeScreen({ status: "pending" }, true).kind).toBe("loading");
    expect(knowledgeScreen({ status: "error", error: 1 }, false).kind).toBe("error");
    expect(knowledgeScreen({ status: "error", error: 1 }, true).kind).toBe("error");
    expect(knowledgeScreen(loaded(golden()), false).kind).toBe("knowledge");
  });

  test("a match just over says that its summary comes within hours; no other reason is a user's to read", () => {
    const fresh = render(loaded(null, {}, "not_settled_yet"), false);
    expect(fresh).toContain('data-testid="knowledge-none"');
    expect(plain(fresh)).toContain("unas horas después del final");
    for (const code of ["not_followed", "no_build_yet", "not_finished"]) {
      expect(render(loaded(null, {}, code), false)).toBe("");
    }
  });

  test("a build with nothing to tell is nothing to a user, and a note to the preview", () => {
    const empty: AfterMatch = {
      ...golden(),
      completeness: "minimal",
      quality: { events_give_the_score: null, doubts: ["no_result"] },
      result: missing(["no_result_row"]),
      team_stats: missing(),
      events: missing(["no_events"]),
      players: missing(),
      tactics: missing(),
      market: missing(),
    };
    expect(render(loaded(empty), false)).toBe("");
    const seen = render(loaded(empty), true);
    expect(seen).toContain('data-completeness="minimal"');
    expect(plain(seen)).toContain("Solo hay el resultado, o ni siquiera eso.");
    expect(plain(seen)).toContain("No tenemos confirmado el resultado de este partido.");
    expect(seen).not.toContain("knowledge-story");
  });
});

// ── the marks of the result ─────────────────────────────────────────────────

describe("the marks a result carries", () => {
  function withMarks(r: Partial<KnowledgeResult>, story: Partial<KnowledgeStory> = {}): AfterMatch {
    const base = golden();
    return {
      ...base,
      result: layer(result(r)),
      tactics: layer({ ...TACTICS, story: { ...STORY, ...story } }),
    };
  }

  test("a win from behind, and a draw from behind", () => {
    const came = headlines(withMarks({ outcome: "Home" }, { ahead: { home: true, away: true } }));
    expect(came).toEqual([{ key: "comeback", side: "home" }]);
    const away = headlines(
      withMarks({ outcome: "Away", reg: [1, 2] }, { ahead: { home: true, away: true } }),
    );
    expect(away).toEqual([{ key: "comeback", side: "away" }]);
    const drew = headlines(
      withMarks({ outcome: "Draw", reg: [1, 1] }, { ahead: { home: true, away: false } }),
    );
    expect(drew).toEqual([{ key: "levelled", side: "away" }]);
    expect(
      headlines(withMarks({ outcome: "Draw", reg: [2, 2] }, { ahead: { home: true, away: true } })),
    ).toEqual([]);
    expect(headlines(golden())).toEqual([]);
  });

  test("said in words, with the team", () => {
    const out = plain(
      render(loaded(withMarks({ outcome: "Home" }, { ahead: { home: true, away: true } })), false),
    );
    expect(out).toContain("Remontada de Nashville SC");
    const levelled = plain(
      render(
        loaded(withMarks({ outcome: "Draw", reg: [1, 1] }, { ahead: { home: false, away: true } })),
        false,
      ),
    );
    expect(levelled).toContain("Nashville SC rescató el empate");
  });

  test("extra time, a shoot-out, neutral ground and a corrected result", () => {
    const extra = headlines(withMarks({ decided_by: "extra_time", final: [3, 2] }));
    expect(extra.map((h) => h.key)).toEqual(["extraTime"]);
    const penalties = headlines(
      withMarks({
        decided_by: "penalties",
        final: [2, 2],
        pen: [4, 3],
        neutral: true,
        corrected: true,
      }),
    );
    expect(penalties.map((h) => h.key)).toEqual(["penalties", "neutral", "corrected"]);
    const out = plain(
      render(loaded(withMarks({ decided_by: "penalties", neutral: true, corrected: true })), false),
    );
    expect(out).toContain("Se resolvió en penales");
    expect(out).toContain("Campo neutral");
    expect(out).toContain("Resultado corregido por el proveedor");
  });

  test("the leg that closed a tie says the aggregate, unless the provider's winner contradicts it", () => {
    const tie = {
      format: "two_legs",
      legs: 2,
      leg: 2,
      aggregate: [3, 2] as [number, number],
      winner: "home" as const,
      decided_by: "aggregate",
      shootout: null,
      contradicted: false,
    };
    expect(plain(render(loaded(withMarks({ tie })), false))).toContain("Global 3–2");
    const contradicted = render(loaded(withMarks({ tie: { ...tie, contradicted: true } })), false);
    expect(contradicted).not.toContain("knowledge-tie");
  });

  test("comebackOf reads the 90 minutes only through who was ahead and how it ended", () => {
    expect(comebackOf({ outcome: "Home" }, { ahead: { home: true, away: false } })).toBeNull();
    expect(comebackOf({ outcome: "Away" }, { ahead: { home: false, away: false } })).toBeNull();
    expect(comebackOf({ outcome: "Draw" }, { ahead: { home: false, away: false } })).toBeNull();
  });
});

// ── the story ───────────────────────────────────────────────────────────────

describe("the story of the score", () => {
  test("the order is the goals', the numbers are the API's: both say the same here", () => {
    const segments = leadTimeline(GOALS);
    expect(segments).toEqual([
      { from: 0, to: 12, state: "level" },
      { from: 12, to: 70, state: "home" },
      { from: 70, to: 85, state: "level" },
      { from: 85, to: 90, state: "home" },
    ]);
    expect(leadMinutes(segments)).toEqual(STORY.minutes);
  });

  test("a second goal of the side that leads does not cut its lead in two", () => {
    expect(leadTimeline([goal(10, "home"), goal(20, "home")])).toEqual([
      { from: 0, to: 10, state: "level" },
      { from: 10, to: 90, state: "home" },
    ]);
  });

  test("stoppage time counts as the 90th minute, extra time and the shoot-out are not part of it", () => {
    const late = { ...goal(90, "away"), extra: 4 };
    expect(leadTimeline([late])).toEqual([{ from: 0, to: 90, state: "level" }]);
    expect(
      leadTimeline([goal(105, "home", "ET"), goal(1, "away", "PEN", "shootout_goal")]),
    ).toEqual([{ from: 0, to: 90, state: "level" }]);
    expect(leadTimeline([])).toEqual([{ from: 0, to: 90, state: "level" }]);
  });

  test("a minute past the 90th inside the regular time (the provider's oddities) is drawn at the 90th", () => {
    expect(leadTimeline([goal(93, "away", "2H")])).toEqual([{ from: 0, to: 90, state: "level" }]);
    expect(trackPercent(93)).toBe(100);
    expect(trackPercent(-3)).toBe(0);
    const drawing = storyDrawing({ minutes: { home_ahead: 0, level: 90, away_ahead: 0 } }, [
      goal(93, "away", "2H"),
    ]);
    expect(drawing.ticks).toEqual([{ minute: 90, side: "away" }]);
  });

  test("goals of the extra time and kicks of the shoot-out are not marked on the 90 minutes", () => {
    const drawing = storyDrawing({ minutes: { home_ahead: 0, level: 90, away_ahead: 0 } }, [
      goal(105, "home", "ET"),
      goal(1, "away", "PEN", "shootout_goal"),
    ]);
    expect(drawing.kind).toBe("timeline");
    expect(drawing.ticks).toEqual([]);
  });

  test("a goal at the same minute as the last one changes the lead without a gap", () => {
    expect(leadTimeline([goal(30, "home"), goal(30, "away"), goal(40, "away")])).toEqual([
      { from: 0, to: 40, state: "level" },
      { from: 40, to: 90, state: "away" },
    ]);
  });

  test("when the goals do not give back the API's count, the totals are drawn as three blocks and no goal is marked", () => {
    const off = { minutes: { home_ahead: 50, level: 30, away_ahead: 10 } };
    const drawing = storyDrawing(off, GOALS);
    expect(drawing.kind).toBe("totals");
    expect(drawing.ticks).toEqual([]);
    expect(drawing.segments).toEqual([
      { from: 0, to: 50, state: "home" },
      { from: 50, to: 80, state: "level" },
      { from: 80, to: 90, state: "away" },
    ]);
    const html = render(
      loaded({
        ...golden(),
        tactics: layer({ ...TACTICS, story: { ...STORY, minutes: off.minutes } }),
      }),
      false,
    );
    expect(html).toContain('data-kind="totals"');
    expect(html).not.toContain("knowledge-goal");
    expect(plain(html)).toContain("Nashville SC por delante 50 min");
  });

  test("a match without a goal says so, and a lone goal is not also the last", () => {
    const none = storyFacts(
      {
        ...STORY,
        first_goal: null,
        last_goal_minute: null,
        lead_changes: 0,
        first_dismissal: null,
      },
      SIDES,
    );
    expect(none.map((f) => f.key)).toEqual(["noGoals"]);
    const one = storyFacts({ ...STORY, last_goal_minute: 12, first_dismissal: null }, SIDES);
    expect(one.map((f) => f.key)).toEqual(["firstGoal", "leadChanges"]);
  });

  test("events that do not give the score: the story is not told, and the page says so", () => {
    const untold: AfterMatch = {
      ...golden(),
      completeness: "partial",
      quality: {
        events_give_the_score: false,
        doubts: ["events_do_not_give_the_score", "odd_minutes", "something_new"],
      },
      tactics: layer({ ...TACTICS, story: null }, "partial", ["story_not_told"]),
    };
    const html = render(loaded(untold), false);
    const words = plain(html);
    expect(html).toContain('data-testid="knowledge-story-untold"');
    expect(html).not.toContain("knowledge-bar");
    expect(words).toContain("No se puede contar cómo fue el marcador");
    expect(html).toContain('data-completeness="partial"');
    expect(words).toContain("Parcial");
    expect(words).toContain("Lo que no pudimos confirmar");
    expect(words).toContain(
      "Los goles de la lista de eventos del proveedor no suman el resultado.",
    );
    expect(words).toContain("Algún evento trae un minuto fuera de lo normal.");
    // a code this page does not know is said once, in plain words
    expect(words).toContain("Hay un dato que no pudimos confirmar.");
  });

  test("a match with no list of events at all says nothing of a story", () => {
    const html = render(
      loaded({
        ...golden(),
        quality: { events_give_the_score: null, doubts: [] },
        events: missing(["no_events"]),
        tactics: layer({ ...TACTICS, story: null }),
      }),
      false,
    );
    expect(html).not.toContain("knowledge-story");
  });

  test("leadText speaks of a side's lead at a moment, and of nothing when the events do not give the score", () => {
    expect(leadText(2)).toBe("ganando por 2");
    expect(leadText(-1)).toBe("perdiendo por 1");
    expect(leadText(0)).toBe("empatando");
    expect(leadText(null)).toBeNull();
    expect(leadText(Number.NaN)).toBeNull();
  });
});

// ── the market ──────────────────────────────────────────────────────────────

describe("the market against what happened", () => {
  test("which selection a result settled", () => {
    const r = { outcome: "Home" as const, total: 3, btts: true };
    expect(cameIn("1X2", r, null)).toEqual({ selection: "Home", pushed: false });
    expect(cameIn("BTTS", { ...r, btts: false }, null)).toEqual({ selection: "No", pushed: false });
    expect(cameIn("OU", r, 2.5)).toEqual({ selection: "Over", pushed: false });
    expect(cameIn("OU", { ...r, total: 2 }, 2.5)).toEqual({ selection: "Under", pushed: false });
    expect(cameIn("OU", r, 3)).toEqual({ selection: null, pushed: true });
    // a quarter line is settled in halves: no one selection came in
    expect(cameIn("OU", r, 2.75)).toEqual({ selection: null, pushed: false });
    expect(cameIn("OU", r, null)).toEqual({ selection: null, pushed: false });
    expect(cameIn("AH", r, -0.5)).toEqual({ selection: null, pushed: false });
  });

  test("a whole line the total landed on is pushed: nothing is marked as having happened", () => {
    const after: AfterMatch = {
      ...golden(),
      market: layer({
        markets: { OU: market({ Over: [0.45, 0.5], Under: [0.55, 0.5] }, { line: 3 }) },
      }),
    };
    const html = render(loaded(after), false);
    expect(plain(html)).toContain("La línea quedó justa: ninguna opción ganó.");
    expect(html).not.toContain('data-happened="true"');
    expect(plain(html)).toContain("Más de 3");
  });

  test("a market read only from the provider's last prices has no probabilities: a user sees none of it", () => {
    const only = market(
      {},
      {
        final: {
          odds: { Home: 1.9 },
          books: 5,
          at: "2026-10-22T23:35:00Z",
          minutes_to_kickoff: 85,
        },
      },
    );
    const after: AfterMatch = {
      ...golden(),
      market: layer({ markets: { "1X2": only } }, "partial"),
    };
    expect(marketReads(after)).toEqual([]);
    const html = render(loaded(after), false);
    expect(html).not.toContain("knowledge-markets");
    expect(html).not.toContain("1,90");
  });

  test("a selection the page does not know is kept after the known ones, in a stable order", () => {
    const after: AfterMatch = {
      ...golden(),
      market: layer({
        markets: {
          "1X2": market({ Away: [0.3, 0.3], Zed: [0.1, 0.1], Home: [0.4, 0.4], Draw: [0.2, 0.2] }),
        },
      }),
    };
    expect(marketReads(after)[0]?.rows.map((r) => r.selection)).toEqual([
      "Home",
      "Draw",
      "Away",
      "Zed",
    ]);
  });

  test("how long before kick-off a reading was", () => {
    expect(beforeKickoff(45)).toBe("45 min");
    expect(beforeKickoff(60)).toBe("1 h");
    expect(beforeKickoff(175)).toBe("2 h 55 min");
    expect(beforeKickoff(-4)).toBe("0 min");
  });

  test("a market that says nothing of its close or its bookmakers does not make them up", () => {
    const after: AfterMatch = {
      ...golden(),
      market: layer({
        markets: {
          "1X2": market(
            { Home: [0.5, 0.5], Draw: [0.25, 0.25], Away: [0.25, 0.25] },
            { books: null, minutes_to_kickoff: null },
          ),
        },
      }),
    };
    const html = render(loaded(after), false);
    expect(html).not.toContain("knowledge-closing");
    const bare: AfterMatch = {
      ...after,
      market: layer({
        markets: {
          "1X2": market(
            { Home: [0.5, 0.5], Away: [0.5, 0.5] },
            { books: null, minutes_to_kickoff: 120 },
          ),
        },
      }),
    };
    expect(plain(render(loaded(bare), false))).toContain(
      "Lectura de cierre: 2 h antes del inicio.",
    );
  });
});

// ── the players and the formations ──────────────────────────────────────────

describe("the best of the match and the formations", () => {
  test("a tie for the best rating shares the mark", () => {
    const after: AfterMatch = {
      ...golden(),
      players: layer({
        ...PLAYERS,
        away: {
          ...AWAY_SIDE,
          top: [
            { player_id: 602, name: "Man 602", rating: 8.4, minutes: 90, goals: 0, assists: 0 },
          ],
        },
      }),
    };
    const best = bestPlayers(after);
    expect(best?.home.map((p) => p.best)).toEqual([true, false, false]);
    expect(best?.away.map((p) => p.best)).toEqual([true]);
  });

  test("only what the provider gave and what is not zero is said of a player", () => {
    expect(playerFigures({ minutes: 90, goals: 0, assists: 0 })).toEqual(["90 min"]);
    expect(playerFigures({ minutes: null, goals: 2, assists: 1 })).toEqual([
      "2 goles",
      "1 asistencia",
    ]);
    expect(playerFigures({ minutes: 0, goals: 0, assists: 0 })).toEqual([]);
  });

  test("a side without a rating list is left out, a match without either is not a part of the page", () => {
    const oneSide: AfterMatch = {
      ...golden(),
      players: layer({ ...PLAYERS, away: null }, "partial", ["no_away"]),
    };
    const html = render(loaded(oneSide), false);
    const section = html.slice(
      html.indexOf('data-testid="knowledge-players"'),
      html.indexOf('data-testid="knowledge-lineups"'),
    );
    expect(section).toContain('data-side="home"');
    expect(section).not.toContain('data-side="away"');
    const none: AfterMatch = { ...golden(), players: missing() };
    expect(bestPlayers(none)).toBeNull();
    expect(render(loaded(none), false)).not.toContain("knowledge-players");
  });

  test("a man the provider could not identify (id 0) is shown by name and has no page to link to", () => {
    expect(hasPlayerPage(501, "Man 501")).toBe(true);
    expect(hasPlayerPage(0, "Man 0")).toBe(false);
    expect(hasPlayerPage(-3, "Man -3")).toBe(false);
    expect(hasPlayerPage(null, "Man")).toBe(false);
    expect(hasPlayerPage(501, null)).toBe(false);
    expect(hasPlayerPage(501, "")).toBe(false);
    const after: AfterMatch = {
      ...golden(),
      players: layer({
        ...PLAYERS,
        home: {
          ...HOME_SIDE,
          top: [{ player_id: 0, name: "Man 0", rating: 9.1, minutes: 90, goals: 0, assists: 0 }],
        },
        away: null,
      }),
    };
    expect(bestPlayers(after)?.home.map((p) => [p.id, p.name, p.best])).toEqual([
      [0, "Man 0", true],
    ]);
    expect(plain(render(loaded(after), false))).toContain("Man 0");
  });

  test("a rating the provider did not give is a dash, never a zero", () => {
    const after: AfterMatch = {
      ...golden(),
      players: layer({
        ...PLAYERS,
        home: {
          ...HOME_SIDE,
          top: [{ player_id: 9, name: "Man 9", rating: null, minutes: 30, goals: 0, assists: 0 }],
        },
        away: null,
      }),
    };
    const words = plain(render(loaded(after), false));
    expect(words).toContain("Man 9");
    expect(words).not.toContain("0,0");
  });

  test("a side that changed no one is told so only when the list of events is there to say it", () => {
    const quiet: AfterMatch = {
      ...golden(),
      tactics: layer({
        home: { formation: "4-3-3", substitutions: [] },
        away: { formation: null, substitutions: [] },
        story: STORY,
      }),
    };
    expect(plain(render(loaded(quiet), false))).toContain("Sin cambios");
    expect(plain(render(loaded(quiet), false))).toContain("Formación no informada");
    const noEvents: AfterMatch = {
      ...quiet,
      events: missing(["no_events"]),
      quality: { events_give_the_score: null, doubts: [] },
    };
    expect(plain(render(loaded(noEvents), false))).not.toContain("Sin cambios");
  });

  test("a side with neither formation nor changes is not a part of the page", () => {
    const after: AfterMatch = {
      ...golden(),
      tactics: layer({ home: null, away: null, story: STORY }),
    };
    expect(lineups(after)).toBeNull();
    expect(render(loaded(after), false)).not.toContain("knowledge-lineups");
  });

  test("changes whose score the events do not give are only a minute", () => {
    const after: AfterMatch = {
      ...golden(),
      tactics: layer({
        home: { formation: "4-3-3", substitutions: [{ minute: 58, lead: null }] },
        away: null,
        story: null,
      }),
    };
    const words = plain(render(loaded(after), false));
    expect(words).toContain("58'");
    expect(words).not.toContain("58' (");
  });
});

// ── the Admin Console's preview ─────────────────────────────────────────────

describe("the Admin Console's preview", () => {
  const html = render(loaded(golden(), { stored: STORED }), true);
  const words = plain(html);

  test("is marked as a preview, and says what it is not", () => {
    expect(html).toContain('data-preview="true"');
    expect(html).toContain("Modo de evaluación");
    expect(html).toContain("No es una recomendación");
    expect(words).toContain("MODO EVALUACIÓN");
  });

  test("sees the same facts a user does", () => {
    for (const id of [
      "knowledge-story",
      "knowledge-markets",
      "knowledge-players",
      "knowledge-lineups",
      "knowledge-quality",
    ]) {
      expect(html).toContain(`data-testid="${id}"`);
    }
  });

  test("folds the row as stored away, after the facts", () => {
    expect(html).toContain("<details");
    expect(html.indexOf('data-testid="knowledge-admin"')).toBeGreaterThan(
      html.indexOf('data-testid="knowledge-quality"'),
    );
    expect(words).toContain("Cómo está guardado (solo administrador)");
    expect(words).toContain("Versión guardada n.º 12");
    expect(words).toContain("reemplaza a la n.º 7");
  });

  test("lists the nine layers, with the decisions and post-mortems only here", () => {
    const names = [
      ...html.matchAll(/data-testid="knowledge-stored-layer" data-layer="([^"]+)"/g),
    ].map((m) => m[1]);
    expect(names).toEqual([
      "c1_result",
      "c2_team_stats",
      "c3_events",
      "c4_players",
      "c5_tactics",
      "c6_market",
      "c7_context",
      "c8_picks",
      "c9_postmortem",
    ]);
    expect(words).toContain("notas: no_BTTS");
    expect(words).toContain("notas: decided_by_the_owner");
    expect(html).toContain("sound_process_bad_luck");
    expect(html).toContain("&quot;picks&quot;");
    // the facts' layers are not dumped: they are already on the page
    expect(html.match(/<pre /g)?.length).toBe(2);
    expect(words).toContain("Las capas 7 a 9");
  });

  test("shows the provider's last prices, which are not probabilities, and the chain of builds", () => {
    expect(html).toContain('data-testid="knowledge-finals"');
    expect(words).toContain(
      "Home 1,85 · Draw 3,60 · Away 4,20 · 14 casas · 1 h 25 min antes del inicio",
    );
    expect(finalReads(golden()).map((f) => f.market)).toEqual(["1X2"]);
    expect(words).toContain("n.º 7");
    expect(words).toContain("n.º 12");
    expect(words).toContain("0f9e8d7c6b5a");
    expect(words).not.toContain("0f9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6");
    expect(shortHash("0f9e8d7c6b5a4938271605f4e3d2c1b0a9f8e7d6")).toBe("0f9e8d7c6b5a");
    const first = plain(
      render(loaded(golden(), { stored: { ...STORED, supersedes: null } }), true),
    );
    expect(first).toContain("primera versión");
  });

  test("storedLayers reads a layer as stored, whatever shape it has", () => {
    const layers = storedLayers({
      layers: { c9_postmortem: { status: 5, notes: [1, "a"], data: { n: 1 } }, c1_result: {} },
    });
    expect(layers.map((l) => l.name)).toEqual(["c1_result", "c9_postmortem"]);
    expect(layers[0]).toEqual({
      name: "c1_result",
      status: "—",
      knownAt: null,
      notes: [],
      json: null,
    });
    expect(layers[1]?.notes).toEqual(["a"]);
    expect(layers[1]?.json).toContain('"n": 1');
  });

  test("shows its own loading, error and reason states", () => {
    const loading = render({ status: "pending" }, true);
    expect(loading).toContain('data-screen="loading"');
    const failed = render({ status: "error", error: new Error("boom") }, true);
    expect(failed).toContain('data-screen="error"');
    expect(failed).toContain('role="alert"');
    const off = render({ status: "success", envelope: envelope(null, "not_available") }, true);
    expect(off).toContain('data-testid="knowledge-none"');
    for (const [code, text] of [
      ["not_finished", "El partido todavía no terminó para el proveedor."],
      ["not_settled_yet", "El postpartido se arma unas horas después del final"],
      ["not_followed", "PrediGol no sigue esta competición"],
      ["no_build_yet", "PrediGol todavía no armó el postpartido de este partido."],
    ] as const) {
      const seen = plain(render(loaded(null, {}, code), true));
      expect(seen).toContain(text);
      expect(seen).not.toContain("PrediGol has not");
      expect(seen).not.toContain("is not over");
    }
    expect(noKnowledgeText("something_new")).toBe(noKnowledgeText(null));
    expect(noKnowledgeText(null).length).toBeGreaterThan(5);
  });
});

// ── the words ───────────────────────────────────────────────────────────────

describe("in English", () => {
  test("the same block, in the reader's language", () => {
    setLocale("en");
    const words = plain(render(loaded(golden()), false));
    expect(words).toContain("After the match");
    expect(words).toContain("Facts, not a recommendation");
    expect(words).toContain("How the score went");
    expect(words).toContain("Nashville SC ahead 63 min");
    expect(words).toContain("First sending-off Inter Miami, 60' (trailing by 1)");
    expect(words).toContain("What the market expected");
    expect(words).toContain("Happened");
    expect(words).toMatch(
      /At the close, the market gave 52% to what happened \(it had opened at 48%\)\./,
    );
    expect(words).toContain("Closing reading: 2 h 55 min before kick-off, from 14 bookmakers.");
    expect(words).toContain("Best of the match");
    expect(words).toContain("Formation 4-3-3");
    expect(words).toContain("58' (leading by 1)");
    expect(words).toContain("Complete");
    expect(words).not.toContain("Postpartido");
    expect(words).not.toContain("por delante");
  });

  test("a mark, a doubt and a reason each have their words", () => {
    setLocale("en");
    expect(plain(render(loaded(null, {}, "not_settled_yet"), false))).toContain(
      "put together a few hours after the final whistle",
    );
    expect(completenessLabel("partial")).toBe("Partial");
    expect(
      doubtTexts({ quality: { events_give_the_score: false, doubts: ["sheets_crossed"] } }),
    ).toEqual([
      "The provider crossed the line-ups of the two teams, so we do not show the formations.",
    ]);
  });
});

describe("the codes the builder can raise have words in both languages", () => {
  /**
   * Every doubt `fbi.knowledge.layers.build` can put in `quality.doubts` (no_result, events_do_not_give_the_score, the
   * events_*_differ of the break, the extra time and the shoot-out, cards_differ_from_the_statistics, sheets_crossed,
   * event_words_not_met, lines_with_no_player, odd_minutes) is listed on the page for a reader; a code without words would be
   * said as "a figure we could not confirm", and that is for a code from the future, not for one of today.
   */
  const DOUBTS = [
    "no_result",
    "events_do_not_give_the_score",
    "events_ht_differ",
    "events_et_differ",
    "events_pen_differ",
    "cards_differ_from_the_statistics",
    "sheets_crossed",
    "event_words_not_met",
    "lines_with_no_player",
    "odd_minutes",
  ];
  /** The reasons `fbi.api.services.knowledge._why_none` can give. */
  const REASONS = ["not_finished", "not_settled_yet", "not_followed", "no_build_yet"];

  test.each(DOUBTS)("the doubt %s has words in both languages", (code) => {
    const es = (esMatch.knowledge.doubt as Record<string, string>)[code];
    const en = (enMatch.knowledge.doubt as Record<string, string>)[code];
    expect(es && es.length > 10).toBe(true);
    expect(en && en.length > 10).toBe(true);
  });

  test.each(REASONS)("the reason %s has words in both languages", (code) => {
    const es = (esMatch.knowledge.reason as Record<string, string>)[code];
    const en = (enMatch.knowledge.reason as Record<string, string>)[code];
    expect(es && es.length > 10).toBe(true);
    expect(en && en.length > 10).toBe(true);
  });

  test("the marks and the completeness each have words", () => {
    for (const key of ["extraTime", "penalties", "comeback", "levelled", "neutral", "corrected"]) {
      expect((esMatch.knowledge.tag as Record<string, string>)[key]).toBeTruthy();
      expect((enMatch.knowledge.tag as Record<string, string>)[key]).toBeTruthy();
    }
    for (const c of ["complete", "partial", "minimal"] as const) {
      expect(completenessLabel(c)).not.toBe(c);
      expect(completenessNote(c).length).toBeGreaterThan(10);
    }
  });
});
