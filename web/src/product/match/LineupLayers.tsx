/**
 * The line-up pitch with data layers (plan PM, PM-10-04, OP-23, lámina I02 «M02»; UX-176): a choice of four layers - rating,
 * minutes, cards, goals and assists - puts one figure of each starter's match on his marker. Drawn instead of the plain pitch only
 * with `FBI_LINEUP_LAYERS` on, player statistics of level B or better (C-16, when it answers) and a statistics line for every starter
 * (`LineupsTab` decides); otherwise the pitch is the line-up alone, as always.
 *
 * An `EvidenceChart` (PM-10-06): E1 (one match), its sentence with the sample and the origin, its «ficha», and the four layers as a
 * table for the team chosen. The label says what the pitch is: the nominal position of the formation, not the real one.
 */
import { useState } from "react";
import { Info } from "lucide-react";
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import { ChipChoice } from "@/components/analytics/stats/ChartCard";
import type { MatchEvent, PlayerLine, Side, TeamLineup } from "@/lib/api/v1/types_center";
import type { TeamRef } from "@/lib/api/v1/types";
import { localInt } from "@/lib/i18n/format";
import {
  LAYERS,
  LINEUP_LAYERS_REVIEW,
  bestRatings,
  goalsAssistsText,
  layerBadge,
  layerFigures,
  tableRows,
  type Layer,
  type LayerFigures,
} from "./layers";
import { fmtDecimal } from "./model";
import { Pitch } from "./Pitch";
import { t } from "./stats/matchvizText";

function cardsText(f: LayerFigures): string {
  const parts: string[] = [];
  if (f.yellow > 0) parts.push(t("matchviz.layers.yellowShort"));
  if (f.red > 0) parts.push(t("matchviz.layers.redShort"));
  return parts.length ? parts.join(" · ") : "—";
}

export function LineupLayers({
  home,
  away,
  teams,
  players,
  events,
  ratings,
}: {
  home: TeamLineup;
  away: TeamLineup;
  teams: { home: TeamRef; away: TeamRef };
  players: readonly PlayerLine[];
  events: readonly MatchEvent[] | null;
  ratings: Map<number, number>;
}) {
  const [layer, setLayer] = useState<Layer>("rating");
  const [side, setSide] = useState<Side>("home");
  const lineups = [home, away];
  const figures = layerFigures(lineups, players, events);
  const best = bestRatings(lineups, figures);
  const words = {
    yellowShort: t("matchviz.layers.yellowShort"),
    redShort: t("matchviz.layers.redShort"),
  };
  const lineup = side === "home" ? home : away;
  const rows = tableRows(lineup, figures);
  const source = t("matchviz.layers.source");
  const formation = (l: TeamLineup, team: TeamRef) =>
    t("matchviz.layers.teamFormation", { team: team.name, formation: l.formation ?? "—" });
  return (
    <EvidenceChart
      testId="lineup-layers"
      title={t("matchviz.layers.title")}
      subtitle={t("matchviz.layers.subtitle")}
      evidence="E1"
      reading={{
        kind: "match",
        subject: t("matchviz.layers.subject", { home: teams.home.name, away: teams.away.name }),
        n: 1,
        source,
        minSample: 1,
      }}
      review={LINEUP_LAYERS_REVIEW}
      method={t("matchviz.layers.method")}
      footer={t("matchviz.footer", { source, n: localInt(1) })}
    >
      <div className="space-y-3">
        <ChipChoice
          value={layer}
          options={LAYERS.map((l) => ({ value: l, label: t(`matchviz.layers.${l}`) }))}
          onChange={setLayer}
          label={t("matchviz.layers.choose")}
          testId="lineup-layer-choice"
        />
        <div data-layer={layer}>
          <Pitch
            home={home}
            away={away}
            teams={teams}
            ratings={ratings}
            badgeOf={(p, s) => layerBadge(layer, figures.get(p.provider_player_id), best[s], words)}
          />
        </div>
        {layer === "rating" ? (
          <p className="text-caption text-muted-foreground">{t("matchviz.layers.bestNote")}</p>
        ) : null}
        {layer === "cards" ? (
          <p className="text-caption text-muted-foreground">{t("matchviz.layers.cardsLegend")}</p>
        ) : null}
        <p
          data-testid="lineup-layers-nominal"
          className="flex items-start gap-2 rounded-lg border border-border bg-elevated/40 px-3 py-2 text-caption text-foreground-soft"
        >
          <Info aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{t("matchviz.layers.nominal")}</span>
        </p>
        <div className="space-y-2">
          <h3 className="text-label text-subtle-foreground">{t("matchviz.layers.tableTitle")}</h3>
          <ChipChoice
            value={side}
            options={[
              { value: "home" as const, label: formation(home, teams.home) },
              { value: "away" as const, label: formation(away, teams.away) },
            ]}
            onChange={setSide}
            label={t("matchviz.layers.team")}
            testId="lineup-layer-team"
          />
          <table
            className="w-full border-collapse text-left text-xs"
            data-testid="lineup-layers-table"
          >
            <caption className="sr-only">
              {`${t("matchviz.layers.tableTitle")} · ${formation(lineup, teams[side])}`}
            </caption>
            <thead>
              <tr className="border-b border-border text-muted-foreground">
                <th scope="col" className="py-1.5 pr-2 font-medium">
                  {t("matchviz.layers.player")}
                </th>
                <th scope="col" className="py-1.5 pr-2 text-right font-medium">
                  {t("matchviz.layers.val")}
                </th>
                <th scope="col" className="py-1.5 pr-2 text-right font-medium">
                  {t("matchviz.layers.min")}
                </th>
                <th scope="col" className="py-1.5 pr-2 text-right font-medium">
                  {t("matchviz.layers.cardsShort")}
                </th>
                <th scope="col" className="py-1.5 text-right font-medium">
                  {t("matchviz.layers.ga")}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ player, f }) => (
                <tr
                  key={player.provider_player_id}
                  className="border-b border-border/60 last:border-0"
                >
                  <th scope="row" className="py-1.5 pr-2 font-normal">
                    <span className="numeric mr-1.5 text-muted-foreground">
                      {player.number ?? ""}
                    </span>
                    {player.name ?? "—"}
                  </th>
                  <td className="numeric py-1.5 pr-2 text-right font-semibold">
                    {f.rating === null ? "—" : fmtDecimal(f.rating, 1)}
                  </td>
                  <td className="numeric py-1.5 pr-2 text-right">
                    {f.minutes === null ? "—" : localInt(f.minutes)}
                  </td>
                  <td className="numeric py-1.5 pr-2 text-right">{cardsText(f)}</td>
                  <td className="numeric py-1.5 text-right">{goalsAssistsText(f)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </EvidenceChart>
  );
}
