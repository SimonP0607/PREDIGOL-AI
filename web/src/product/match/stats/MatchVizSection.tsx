/**
 * The Match Center's new pieces of plan PM, block 10, at the top of Estadísticas once the match is under way (lámina I01): the
 * shot funnel and its two zones (PM-10-01; FE-005). Each piece behind its own switch, read in `/auth/me` and off by default:
 * off, nothing here is drawn and the tab is as it was. A piece is drawn only when C-16 lets its block be (level B or better, when
 * C-16 answers) and the match delivered every figure it needs: never an empty card.
 */
import { useMatchVizSwitches } from "@/lib/auth/AuthProvider";
import type { MatchCtx } from "../context";
import { blockAllows, useMatchBlocks } from "./coverage";
import { t } from "./matchvizText";
import { ShotFunnelCard, ShotZonesCard } from "./ShotFunnel";
import { shotFunnel, shotZones, statSource } from "./shots";

export function MatchVizSection({ ctx }: { ctx: MatchCtx }) {
  const switches = useMatchVizSwitches();
  const blocks = useMatchBlocks(ctx.fixtureId);
  if (!switches.shotFunnel) return null;
  const data = ctx.center.data;
  if (!data || data.statistics.status !== "ok") return null;
  if (blockAllows(blocks, "team_stats") === false) return null;
  const lines = data.statistics.data;
  const events = data.events.status === "ok" ? data.events.data : null;
  const funnel = shotFunnel(lines, events, ctx.score);
  const zones = shotZones(lines);
  if (!funnel && !zones) return null;
  const teams = { home: ctx.match.home, away: ctx.match.away };
  const source = t(`matchviz.source.${statSource(lines)}`);
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
    </div>
  );
}
