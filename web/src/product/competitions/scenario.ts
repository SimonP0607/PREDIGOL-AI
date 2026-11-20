/**
 * The calculator «¿Qué pasa si…?» (plan PM, PM-09-03; UX-181; lámina I07, M05): the reader picks the result of matches still to be
 * played and sees how a season table would end - computed in the browser from what the server sends (BE-082: the rows, the points
 * a win, a draw and a loss give, the matches each table counts). A chosen result adds its points; a score is never invented, so two
 * clubs left level on points (or on the exact average) are said to be level - the regulation's tie-breakers decide, and goals are
 * not something the reader chose. It estimates nothing: no model, no probability. The same cases run on the server
 * (`backend/tests/fixtures/competitions/what_if_cases.json`, checked with `fbi.competitions.ranking`).
 */
export type Choice = "home" | "draw" | "away";
export type TableKind = "aggregate" | "average";

export interface WhatIfRow {
  team: number;
  played: number;
  points: number;
  /** An average only: whether the club's average counts the current season (its window). */
  counts_now?: boolean | undefined;
}

export interface PointsRule {
  win: number;
  draw: number;
  loss: number;
}

export interface WhatIfLine {
  team: number;
  points: number;
  played: number;
  position: number;
  /** Level with another club on points (on the exact average): the regulation decides, not this calculator. */
  tied: boolean;
  /** The position before the chosen results. */
  before: number;
}

function points(choice: Choice, side: "home" | "away", rule: PointsRule): number {
  if (choice === "draw") return rule.draw;
  return choice === side ? rule.win : rule.loss;
}

/** -1 when a ranks above b. An average compares the exact quotients (cross-multiplied: no rounding ever decides). */
function compare(kind: TableKind, a: WhatIfRow, b: WhatIfRow): number {
  if (kind === "aggregate") return b.points - a.points;
  if (a.played === 0 || b.played === 0) {
    const av = a.played === 0 ? 0 : a.points / a.played;
    const bv = b.played === 0 ? 0 : b.points / b.played;
    return bv - av;
  }
  return b.points * a.played - a.points * b.played;
}

/**
 * The table after the chosen results. `remaining[i]` is a match as [home, away]; `choices[i]` its chosen result (a match left
 * out is not counted). Clubs level keep the order they had: the regulation's tie-breakers, not the calculator, separate them.
 */
export function applyChoices(
  kind: TableKind,
  rows: readonly WhatIfRow[],
  remaining: ReadonlyArray<readonly [number, number]>,
  choices: Readonly<Record<string, Choice | undefined>>,
  rule: PointsRule,
): WhatIfLine[] {
  const now = new Map(rows.map((r) => [r.team, { ...r }]));
  for (const [i, choice] of Object.entries(choices)) {
    if (!choice) continue;
    const match = remaining[Number(i)];
    if (!match) continue;
    const [home, away] = match;
    for (const [team, side] of [
      [home, "home"],
      [away, "away"],
    ] as const) {
      const row = now.get(team);
      if (!row) continue;
      if (kind === "average" && row.counts_now === false) continue;
      row.points += points(choice, side, rule);
      row.played += 1;
    }
  }
  const order = rows.map((r) => r.team);
  const sorted = [...now.values()].sort(
    (a, b) => compare(kind, a, b) || order.indexOf(a.team) - order.indexOf(b.team),
  );
  return sorted.map((r, i) => ({
    team: r.team,
    points: r.points,
    played: r.played,
    position: i + 1,
    tied: sorted.some((o) => o.team !== r.team && compare(kind, o, r) === 0),
    before: order.indexOf(r.team) + 1,
  }));
}

export interface ZoneShift {
  zone: number;
  entered: number[];
  left: number[];
}

/** Who enters and who leaves each zone (by its positions) between the table of today and the reader's scenario. */
export function zoneShifts(
  zones: ReadonlyArray<{ positions: readonly number[] }>,
  before: readonly number[],
  after: readonly number[],
): ZoneShift[] {
  return zones
    .map((z, zone) => {
      const was = new Set(z.positions.map((p) => before[p - 1]).filter((x) => x !== undefined));
      const is = new Set(z.positions.map((p) => after[p - 1]).filter((x) => x !== undefined));
      return {
        zone,
        entered: [...is].filter((t) => !was.has(t)) as number[],
        left: [...was].filter((t) => !is.has(t)) as number[],
      };
    })
    .filter((s) => s.entered.length > 0 || s.left.length > 0);
}
