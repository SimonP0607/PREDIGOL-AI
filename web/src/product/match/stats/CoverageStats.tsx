/**
 * Estadísticas of a match whose competition does not deliver team statistics at level B (plan PM, PM-14-02, lámina I04; UX-177):
 * instead of a card of figures that would be empty, what the competition does deliver - the facts of the match sheet from its
 * events (lámina I04 «B»), one note that says what it does not offer and why (the shared «información no disponible», PM-14-01), and
 * the teams' last five results and the season's table (lámina I04 «C» and «D»). Only with `FBI_MATCH_COVERAGE` on and C-16
 * answering (`StatsTab` decides). The strip of the score's state, where the events are, is drawn above by `MatchVizSection`.
 */
import { ClipboardList } from "lucide-react";
import type { BlockAvailability } from "@/lib/api/v1/types_availability";
import type { MatchEvent } from "@/lib/api/v1/types_center";
import { blockUnavailable } from "@/product/shared/availabilityState";
import { UnavailableNotes } from "@/product/shared/Unavailable";
import type { MatchCtx } from "../context";
import { FormBlock, StandingsBlock } from "../ContextBlocks";
import { eventKind, goalCredit, isScoring, type Goals, type StatRow } from "../model";
import { Block, StatBars, TeamsLegend } from "../ui";
import { blockAllows, type MatchBlockKey } from "./coverage";
import { t } from "./matchvizText";

/** The blocks whose absence the note names, in the lámina's words. */
const NOTED: readonly MatchBlockKey[] = ["lineups", "team_stats", "player_stats"];

/**
 * The facts of the match sheet from its events: goals, yellow and red cards, substitutions per side. Null without events; the goals
 * are the score's when the events do not add up to it.
 */
export function actFacts(
  events: readonly MatchEvent[] | null,
  score: Goals | null,
): StatRow[] | null {
  if (!events || events.length === 0) return null;
  const tally = {
    yellow: { home: 0, away: 0 },
    red: { home: 0, away: 0 },
    subs: { home: 0, away: 0 },
  };
  for (const e of events) {
    if (e.side !== "home" && e.side !== "away") continue;
    const kind = eventKind(e);
    if (kind === "yellow") tally.yellow[e.side] += 1;
    else if (kind === "red" || kind === "secondYellow") tally.red[e.side] += 1;
    else if (kind === "sub") tally.subs[e.side] += 1;
  }
  const play = events.filter((e) => !(e.comments ?? "").toLowerCase().includes("shootout"));
  const { credit, reliable } = goalCredit(play, score);
  let goals: Goals | null = score;
  if (reliable) {
    goals = { home: 0, away: 0 };
    for (const e of play) {
      const to = credit.get(e.seq);
      if (to && isScoring(eventKind(e))) goals[to] += 1;
    }
  }
  const rows: StatRow[] = [];
  if (goals) rows.push({ key: "goals", format: "int", home: goals.home, away: goals.away });
  rows.push({ key: "yellow", format: "int", ...tally.yellow });
  rows.push({ key: "red", format: "int", ...tally.red });
  rows.push({ key: "subs", format: "int", ...tally.subs });
  return rows;
}

/** One note for what the competition does not offer (grouped by state: never one per block, lámina I12). */
export function coverageNotes(blocks: readonly BlockAvailability[]) {
  return NOTED.flatMap((key) => {
    const block = blocks.find((b) => b.key === key);
    if (!block) return [];
    return [{ subject: t(`matchviz.coverage.subject.${key}`), state: blockUnavailable(block) }];
  });
}

export function CoverageStats({
  ctx,
  blocks,
}: {
  ctx: MatchCtx;
  blocks: readonly BlockAvailability[];
}) {
  const data = ctx.center.data;
  const events = data?.events.status === "ok" ? data.events.data : null;
  const facts =
    ctx.phase !== "scheduled" && blockAllows(blocks, "events") !== false
      ? actFacts(events, ctx.score)
      : null;
  return (
    <div className="space-y-4" data-testid="coverage-stats">
      {facts ? (
        <Block title={t("matchviz.coverage.facts")} icon={<ClipboardList />}>
          <div className="space-y-4">
            <TeamsLegend home={ctx.match.home} away={ctx.match.away} />
            <StatBars rows={facts} labelOf={(r) => t(`matchviz.coverage.fact.${r.key}`)} />
            <p className="text-caption text-muted-foreground">{t("matchviz.coverage.factsNote")}</p>
          </div>
        </Block>
      ) : null}
      <UnavailableNotes entries={coverageNotes(blocks)} />
      <div className="grid items-start gap-4 lg:grid-cols-2">
        <FormBlock ctx={ctx} />
        <StandingsBlock ctx={ctx} />
      </div>
    </div>
  );
}
