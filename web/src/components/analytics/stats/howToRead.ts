/**
 * «Cómo leerlo» for the statistics of a team (plan Correcciones UX, AP-T03): one sentence per chart, written from the figures the
 * contract (C-13) already computed - the team's name, the sample, the best and the weakest stretch. Nothing here calculates a
 * statistic: it picks the extreme the server sent and puts it in words. A chart with no data gives no sentence (the page shows the
 * reason instead of an empty drawing). Pure.
 */
import { localFixed, localInt } from "@/lib/i18n/format";
import { t as translate } from "@/lib/i18n";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type {
  ScatterPoint,
  PlayerBody,
  GameStates,
  GoalIntervals,
  HalfSplit,
  MatchPoint,
  Pulse,
  PulseBin,
  RadarAxis,
  StatFigure,
  StripItem,
  TeamRecord,
  Survival,
  TrendRow,
} from "@/lib/api/v1/types_stats";
import type { TextReading } from "../evidence";
import { figName, goodness } from "./format";
import { t } from "./readText";

/** Under this many matches a team's chart is an anecdote (it caps the evidence level at E0). */
export const MIN_MATCHES = 5;

function reading(
  sentence: string,
  n: number,
  minSample = MIN_MATCHES,
  thinKey = "readchart.thin",
): TextReading {
  const thin = n < minSample;
  return {
    kind: "text",
    sentence: thin ? `${sentence} ${t(thinKey, { n: localInt(n) })}` : sentence,
    n,
    minSample,
  };
}

/** «mejor que el 63 % de su liga»: the place of a figure in its league, said in words (the percentile is higher-is-better). */
export function placeInWords(good: number): string {
  const rounded = Math.round(good);
  if (rounded === 50) return t("readchart.words.middle");
  return rounded > 50
    ? t("readchart.words.better", { pct: localInt(rounded) })
    : t("readchart.words.worse", { pct: localInt(100 - rounded) });
}

/** The label of a pulse or interval bin as a reader says it: «los minutos 46–50», «el tiempo añadido del primer tiempo». */
export function slotWords(label: string): string {
  if (label === "45+") return t("readchart.slot.added1");
  if (label === "90+") return t("readchart.slot.added2");
  return t("readchart.slot.range", { label: label.replace("-", "–") });
}

export function performanceReading(
  team: string,
  figures: StatFigure[],
  matches: number,
  teams: number | string,
): TextReading {
  const placed = figures
    .map((f) => ({ f, good: goodness(f) }))
    .filter((x): x is { f: StatFigure; good: number } => x.good !== null);
  const n = String(teams);
  if (placed.length === 0) return reading(t("readchart.perf.none", { team }), matches);
  const best = placed.reduce((a, b) => (b.good > a.good ? b : a));
  const worst = placed.reduce((a, b) => (b.good < a.good ? b : a));
  if (best.f.key === worst.f.key)
    return reading(
      t("readchart.perf.one", {
        team,
        fig: figName(best.f.key),
        words: placeInWords(best.good),
        teams: n,
        n: localInt(matches),
      }),
      matches,
    );
  return reading(
    t("readchart.perf.read", {
      team,
      best: figName(best.f.key),
      bestWords: placeInWords(best.good),
      worst: figName(worst.f.key),
      worstWords: placeInWords(worst.good),
      teams: n,
      n: localInt(matches),
    }),
    matches,
  );
}

export function statesReading(team: string, s: GameStates): TextReading {
  return reading(
    t("readchart.states.read", {
      team,
      won: localInt(s.minutes_leading),
      level: localInt(s.minutes_level),
      lost: localInt(s.minutes_trailing),
      n: localInt(s.matches_with_data),
    }),
    s.matches_with_data,
  );
}

function indexed(p: Pulse): Array<PulseBin & { index: number }> {
  return p.bins.filter((b): b is PulseBin & { index: number } => !isMissing(b.index));
}

/** The team's goals (scored, then conceded): its best stretch against the league's 100, or that it never beats it. */
export function pulseReading(team: string, scored: Pulse, conceded: Pulse | null): TextReading {
  const bins = indexed(scored);
  const n = scored.matches;
  const top = bins.reduce<(PulseBin & { index: number }) | null>(
    (a, b) => (a === null || b.index > a.index ? b : a),
    null,
  );
  if (!top || top.index <= 100)
    return reading(t("readchart.pulse.flat", { team, n: localInt(n) }), n);
  const low = bins.reduce((a, b) => (b.index < a.index ? b : a));
  const sentence = t("readchart.pulse.readFor", {
    team,
    pct: localInt(Math.round(top.index - 100)),
    slot: slotWords(top.label),
    low: slotWords(low.label),
    n: localInt(n),
  });
  const worst = conceded
    ? indexed(conceded).reduce<(PulseBin & { index: number }) | null>(
        (a, b) => (a === null || b.index > a.index ? b : a),
        null,
      )
    : null;
  return reading(
    worst && worst.index > 100
      ? `${sentence} ${t("readchart.pulse.readAgainst", {
          team,
          pct: localInt(Math.round(worst.index - 100)),
          slot: slotWords(worst.label),
          n: localInt(conceded?.matches ?? n),
        })}`
      : sentence,
    n,
  );
}

export function intervalsReading(team: string, iv: GoalIntervals): TextReading {
  const n = iv.matches;
  const tf = iv.bins.reduce((a, b) => a + b.goals_for, 0);
  const ta = iv.bins.reduce((a, b) => a + b.goals_against, 0);
  const top = iv.bins.reduce<GoalIntervals["bins"][number] | null>((a, b) => {
    const gap = b.goals_for - b.league_for * n;
    return a === null || gap > a.goals_for - a.league_for * n ? b : a;
  }, null);
  if (!top)
    return reading(
      t("readchart.intervals.read", { team, slot: "—", gf: 0, ga: 0, lf: 0, tf, ta, n }),
      n,
    );
  return reading(
    t("readchart.intervals.read", {
      team,
      slot: slotWords(top.label),
      gf: localInt(top.goals_for),
      ga: localInt(top.goals_against),
      lf: localFixed(top.league_for * n, 1),
      tf: localInt(tf),
      ta: localInt(ta),
      n: localInt(n),
    }),
    n,
  );
}

export function survivalReading(team: string, s: Survival): TextReading {
  const n = localInt(s.matches);
  if (isMissing(s.median_first_goal))
    return reading(t("readchart.survival.none", { team, n }), s.matches);
  return reading(
    t("readchart.survival.read", {
      team,
      median: s.median_first_goal,
      half: isMissing(s.level_at_half) ? "—" : localInt(Math.round(s.level_at_half * 100)),
      n,
    }),
    s.matches,
  );
}

/** The latest 5-match averages of xG; null when the league gives no xG (the chart is then not drawn). */
export function xgPoint(series: MatchPoint[]): { xf: number; xa: number } | null {
  for (let i = series.length - 1; i >= 0; i--) {
    const p = series[i]!;
    const xf = p.xg_for_avg5;
    const xa = p.xg_against_avg5;
    if (typeof xf === "number" && typeof xa === "number") return { xf, xa };
  }
  return null;
}

export function xgReading(team: string, series: MatchPoint[]): TextReading | null {
  const p = xgPoint(series);
  if (!p) return null;
  return reading(
    t("readchart.xg.read", { team, xf: localFixed(p.xf, 2), xa: localFixed(p.xa, 2) }),
    series.length,
  );
}

export function halvesReading(team: string, h: HalfSplit): TextReading {
  return reading(
    t("readchart.halves.read", {
      team,
      f1: localInt(h.goals_for_1h),
      f2: localInt(h.goals_for_2h),
      a1: localInt(h.goals_against_1h),
      a2: localInt(h.goals_against_2h),
      n: localInt(h.matches_with_data),
    }),
    h.matches_with_data,
  );
}

export function radarReading(team: string, axes: RadarAxis[], matches: number): TextReading {
  const placed = axes.filter(
    (a): a is RadarAxis & { percentile: number } => !isMissing(a.percentile),
  );
  if (placed.length < 2) return reading(t("readchart.perf.none", { team }), matches);
  const best = placed.reduce((a, b) => (b.percentile > a.percentile ? b : a));
  const worst = placed.reduce((a, b) => (b.percentile < a.percentile ? b : a));
  return reading(
    t("readchart.radar.read", {
      team,
      best: translate(`stats.axis.${best.key}`),
      bestWords: placeInWords(best.percentile),
      worst: translate(`stats.axis.${worst.key}`),
      worstWords: placeInWords(worst.percentile),
    }),
    matches,
  );
}

export function trendsReading(team: string, rows: TrendRow[], matches: number): TextReading | null {
  const dev = rows.filter(
    (r): r is TrendRow & { deviation_pts: number; league_pct: number } =>
      !isMissing(r.deviation_pts) && !isMissing(r.league_pct),
  );
  if (dev.length === 0) return null;
  const top = dev.reduce((a, b) => (Math.abs(b.deviation_pts) > Math.abs(a.deviation_pts) ? b : a));
  return reading(
    t("readchart.trends.read", {
      team,
      label: translate(`stats.trend.${top.key}`),
      pct: localInt(Math.round(top.pct)),
      n: localInt(top.n),
      league: localInt(Math.round(top.league_pct)),
    }),
    matches,
  );
}

/** The place of one figure in words, turned round for a figure where less is better; null when the server sent no percentile. */
export function figurePlace(f: StatFigure): string | null {
  const good = goodness(f);
  return good === null ? null : placeInWords(good);
}

function extremes(figures: StatFigure[]) {
  const placed = figures
    .map((f) => ({ f, good: goodness(f) }))
    .filter((x): x is { f: StatFigure; good: number } => x.good !== null);
  if (placed.length === 0) return null;
  return {
    best: placed.reduce((a, b) => (b.good > a.good ? b : a)),
    worst: placed.reduce((a, b) => (b.good < a.good ? b : a)),
    count: placed.length,
  };
}

/** A player against the league's players of his position: his best and his weakest figure, with the 90 minutes behind them. */
export function playerReading(p: PlayerBody, position: string): TextReading {
  const nineties = Math.floor(p.nineties);
  const e = extremes(p.figures);
  const minSample = Math.ceil(p.min_nineties);
  if (!e)
    return reading(
      t("readchart.player.none", { name: p.player.name }),
      nineties,
      minSample,
      "readchart.thinPlayer",
    );
  return reading(
    t(e.best.f.key === e.worst.f.key ? "readchart.player.one" : "readchart.player.read", {
      name: p.player.name,
      position,
      best: figName(e.best.f.key),
      bestWords: placeInWords(e.best.good),
      worst: figName(e.worst.f.key),
      worstWords: placeInWords(e.worst.good),
      n: localInt(nineties),
    }),
    nineties,
    minSample,
    "readchart.thinPlayer",
  );
}

/** One metric over the last appearances: the values the server sent and their mean (the strip itself shows the mean). */
export function lastFiveReading(name: string, strip: StripItem[], metric: string): TextReading {
  const values = strip.map((s) => s.values.find((v) => v.key === metric)?.value);
  const known = values.filter((v): v is number => typeof v === "number");
  const mean = known.length ? known.reduce((a, b) => a + b, 0) / known.length : null;
  if (mean === null)
    return reading(t("readchart.last5.none", { name, fig: figName(metric) }), known.length, 3);
  return reading(
    t("readchart.last5.read", {
      name,
      fig: figName(metric),
      n: localInt(known.length),
      values: values
        .map((v) => (typeof v === "number" ? localFixed(v, v % 1 ? 1 : 0) : "—"))
        .join(" · "),
      mean: localFixed(mean, 1),
    }),
    known.length,
    3,
  );
}

export function minutesReading(p: PlayerBody): TextReading {
  const sum = p.recent_minutes.reduce((a, m) => a + m.minutes, 0);
  return reading(
    t("readchart.minutes.read", {
      name: p.player.name,
      starts: localInt(p.starts),
      of: localInt(p.appearances),
      k: localInt(p.recent_minutes.length),
      sum: localInt(sum),
    }),
    p.recent_minutes.length,
    3,
  );
}

/** Two teams' radars: the aspect where they differ most, with where each one sits in its league. */
export function compareRadarReading(
  a: { name: string; axes: RadarAxis[] },
  b: { name: string; axes: RadarAxis[] },
  matches: number,
): TextReading {
  const pairs = a.axes
    .map((x) => ({
      key: x.key,
      pa: x.percentile,
      pb: b.axes.find((y) => y.key === x.key)?.percentile,
    }))
    .filter(
      (x): x is { key: RadarAxis["key"]; pa: number; pb: number } =>
        typeof x.pa === "number" && typeof x.pb === "number",
    );
  if (pairs.length === 0)
    return reading(t("readchart.compareRadar.none", { a: a.name, b: b.name }), matches);
  const top = pairs.reduce((m, x) => (Math.abs(x.pa - x.pb) > Math.abs(m.pa - m.pb) ? x : m));
  return reading(
    t("readchart.compareRadar.read", {
      a: a.name,
      b: b.name,
      axis: translate(`stats.axis.${top.key}`),
      aWords: placeInWords(top.pa),
      bWords: placeInWords(top.pb),
    }),
    matches,
  );
}

/** Two players on the same position's figures: the figure where they are furthest apart. */
export function comparePlayersReading(a: PlayerBody, b: PlayerBody): TextReading {
  const nineties = Math.floor(Math.min(a.nineties, b.nineties));
  const minSample = Math.ceil(Math.max(a.min_nineties, b.min_nineties));
  const pairs = a.figures
    .map((fa) => ({ fa, fb: b.figures.find((f) => f.key === fa.key) }))
    .map(({ fa, fb }) => ({ fa, fb, ga: goodness(fa), gb: fb ? goodness(fb) : null }))
    .filter(
      (x): x is { fa: StatFigure; fb: StatFigure; ga: number; gb: number } =>
        x.fb !== undefined && x.ga !== null && x.gb !== null,
    );
  if (pairs.length === 0)
    return reading(
      t("readchart.comparePlayers.none", { a: a.player.name, b: b.player.name }),
      nineties,
      minSample,
      "readchart.thinPlayer",
    );
  const top = pairs.reduce((m, x) => (Math.abs(x.ga - x.gb) > Math.abs(m.ga - m.gb) ? x : m));
  return reading(
    t("readchart.comparePlayers.read", {
      a: a.player.name,
      b: b.player.name,
      fig: figName(top.fa.key),
      aWords: placeInWords(top.ga),
      bWords: placeInWords(top.gb),
    }),
    nineties,
    minSample,
    "readchart.thinPlayer",
  );
}

/** Two players' shots and accuracy, as the server sent them (null when one of them has no point). */
export function scatterReading(
  a: { name: string; point: ScatterPoint | null },
  b: { name: string; point: ScatterPoint | null },
  nineties: number,
  minSample: number,
): TextReading | null {
  if (!a.point || !b.point) return null;
  return reading(
    t("readchart.scatter.read", {
      a: a.name,
      b: b.name,
      pa: localFixed(a.point.shots_per90, 1),
      ta: localFixed(a.point.on_target_pct, 0),
      pb: localFixed(b.point.shots_per90, 1),
      tb: localFixed(b.point.on_target_pct, 0),
    }),
    nineties,
    minSample,
    "readchart.thinPlayer",
  );
}

/** The readings of the same chart for each team (home, then away) said one after the other; the smallest sample caps the level. */
export function together(readings: TextReading[]): TextReading {
  return {
    kind: "text",
    sentence: readings.map((r) => r.sentence).join(" "),
    n: Math.min(...readings.map((r) => r.n)),
    minSample: Math.max(...readings.map((r) => r.minSample)),
  };
}

/** The three sentences at the top of a team's statistics (AP-E03): its form, its strength and its weak point, from the contract's own figures. */
export function teamSummary(
  team: string,
  record: TeamRecord,
  figures: StatFigure[],
): { form: string; strength: string | null; weakness: string | null } {
  const e = extremes(figures);
  const form = t("readchart.summary.form", {
    team,
    n: localInt(record.matches),
    won: localInt(record.wins),
    drawn: localInt(record.draws),
    lost: localInt(record.losses),
    gf: localInt(record.goals_for),
    ga: localInt(record.goals_against),
  });
  if (!e || e.best.f.key === e.worst.f.key) return { form, strength: null, weakness: null };
  return {
    form,
    strength: t("readchart.summary.strength", {
      fig: figName(e.best.f.key),
      words: placeInWords(e.best.good),
    }),
    weakness: t("readchart.summary.weakness", {
      fig: figName(e.worst.f.key),
      words: placeInWords(e.worst.good),
    }),
  };
}
