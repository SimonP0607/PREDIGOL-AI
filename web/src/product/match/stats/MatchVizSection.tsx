/**
 * The Match Center's new pieces of plan PM, block 10, at the top of Estadísticas once the match is under way (lámina I01), in the
 * lámina's order: the shot funnel and its two zones (PM-10-01; FE-005), the balance of the match and the strip of the score's
 * state (PM-10-02; FE-006), the statistics by half (PM-10-03; FE-010). Each piece behind its own switch, read in `/auth/me` and off by default: off, nothing here is drawn and
 * the tab is as it was. A piece is drawn only when C-16 lets its block be (level B or better, when C-16 answers) and the match
 * delivered every figure it needs: never an empty card. The strip needs the events (it is what a level C competition shows) and a
 * finished match: while it is played, who was ahead until the 90th is not known yet.
 */
import { useMatchVizSwitches } from "@/lib/auth/AuthProvider";
import type { MatchCtx } from "../context";
import { balanceRows, scoreState } from "./balance";
import { blockAllows, useMatchBlocks } from "./coverage";
import { BalanceCard, ScoreStateCard } from "./MatchBalance";
import { t } from "./matchvizText";
import { PeriodStats } from "./PeriodStats";
import { ShotFunnelCard, ShotZonesCard } from "./ShotFunnel";
import { shotFunnel, shotZones, statSource } from "./shots";

export function MatchVizSection({ ctx }: { ctx: MatchCtx }) {
  const switches = useMatchVizSwitches();
  const blocks = useMatchBlocks(ctx.fixtureId);
  if (!switches.shotFunnel && !switches.balance && !switches.halves) return null;
  const data = ctx.center.data;
  if (!data) return null;
  const teams = { home: ctx.match.home, away: ctx.match.away };
  const statsOk = data.statistics.status === "ok" && blockAllows(blocks, "team_stats") !== false;
  const lines = data.statistics.status === "ok" ? data.statistics.data : [];
  const events = data.events.status === "ok" ? data.events.data : null;
  const source = t(`matchviz.source.${statSource(lines)}`);

  const funnel = switches.shotFunnel && statsOk ? shotFunnel(lines, events, ctx.score) : null;
  const zones = switches.shotFunnel && statsOk ? shotZones(lines) : null;
  const balance = switches.balance && statsOk ? balanceRows(lines) : null;
  const s = ctx.match.score;
  const state =
    switches.balance && ctx.phase === "finished" && blockAllows(blocks, "events") !== false
      ? scoreState(events, ctx.score, s ? s.et_home !== null || s.pen_home !== null : false)
      : null;
  // PM-10-03: the halves, behind their own switch, from the match's own answer (C-16 says whether the block exists at all)
  const halves = switches.halves && statsOk && ctx.phase !== "live";
  if (!funnel && !zones && !balance && !state && !halves) return null;
  return (
    <div data-testid="match-viz" className="grid items-start gap-4 lg:grid-cols-2">
      {funnel ? <ShotFunnelCard funnel={funnel} teams={teams} source={source} /> : null}
      {zones ? (
        <ShotZonesCard
          zones={zones}
          teams={teams}
          source={source}
          shots={funnel ? { home: funnel.home.shots, away: funnel.away.shots } : undefined}
        />
      ) : null}
      {balance ? <BalanceCard rows={balance} teams={teams} source={source} /> : null}
      {state ? <ScoreStateCard state={state} teams={teams} /> : null}
      {halves ? <PeriodStats fixtureId={ctx.fixtureId} teams={teams} /> : null}
    </div>
  );
}
