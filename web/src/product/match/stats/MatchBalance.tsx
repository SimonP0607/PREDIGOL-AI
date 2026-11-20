/**
 * «Balanza del partido» and «Estado del marcador» (plan PM, PM-10-02, OP-25, lámina I01 «M04»; FE-006). Drawn only with
 * `FBI_MATCH_BALANCE` on (the page decides: `MatchVizSection`): the balance where the team statistics are of level B or better, the
 * strip where the events are (level C shows the strip alone, lámina I04).
 *
 * Each card is an `EvidenceChart` (PM-10-06): E1 (one match), its sentence with the sample and the origin, its «ficha» and the same
 * figures as a table. The balance is the system's `StatBars`, each bar the side's share of the pair; the strip is the Postpartido's
 * `StoryBar`, the same drawing and count.
 */
import { Info } from "lucide-react";
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import { t as tr } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { fmtStat, type StatRow } from "../model";
import { StoryBar } from "../StoryBar";
import { StatBars, TeamsLegend } from "../ui";
import { MATCH_BALANCE_REVIEW, pairShare, type ScoreState } from "./balance";
import { t } from "./matchvizText";
import { EquivalentTable, type FunnelTeams } from "./ShotFunnel";

/** «Balanza del partido»: possession, shots, shots in the box and corners shared out between the two sides. */
export function BalanceCard({
  rows,
  teams,
  source,
}: {
  rows: StatRow[];
  teams: FunnelTeams;
  source: string;
}) {
  const label = (r: StatRow) => t(`matchviz.balance.${r.key}`);
  return (
    <EvidenceChart
      testId="match-balance"
      title={t("matchviz.balance.title")}
      evidence="E1"
      reading={{
        kind: "match",
        subject: t("matchviz.balance.subject", { home: teams.home.name, away: teams.away.name }),
        n: 1,
        source,
        minSample: 1,
      }}
      review={MATCH_BALANCE_REVIEW}
      method={t("matchviz.balance.method")}
      footer={t("matchviz.footer", { source, n: localInt(1) })}
    >
      <div className="space-y-4">
        <p
          data-testid="match-balance-badge"
          className="inline-flex items-center gap-1.5 rounded-full border border-border-strong bg-elevated px-2.5 py-1 text-caption font-medium text-foreground-soft"
        >
          <Info aria-hidden className="h-3.5 w-3.5 shrink-0" />
          {t("matchviz.balance.badge")}
        </p>
        <TeamsLegend home={teams.home} away={teams.away} />
        <ul className="sr-only">
          {rows.map((r) => (
            <li key={r.key}>
              {t("matchviz.balance.aria", {
                label: label(r),
                home: teams.home.name,
                homeValue: fmtStat(r.home, r.format),
                away: teams.away.name,
                awayValue: fmtStat(r.away, r.format),
              })}
            </li>
          ))}
        </ul>
        <div aria-hidden>
          <StatBars rows={rows} labelOf={label} widthOf={pairShare} />
        </div>
        <p className="text-caption text-muted-foreground">{t("matchviz.balance.note")}</p>
        <EquivalentTable
          caption={t("matchviz.balance.title")}
          teams={teams}
          rows={rows.map((r) => ({
            key: r.key,
            label: label(r),
            home: fmtStat(r.home, r.format),
            away: fmtStat(r.away, r.format),
          }))}
        />
      </div>
    </EvidenceChart>
  );
}

/** «Estado del marcador»: who was ahead over the 90 minutes, and for how long - the three states, a zero included. */
export function ScoreStateCard({ state, teams }: { state: ScoreState; teams: FunnelTeams }) {
  const source = t("matchviz.scoreState.source");
  const sides = { home: teams.home.name, away: teams.away.name };
  const m = state.drawing.minutes;
  const spans = [
    {
      key: "home",
      label: tr("match.knowledge.story.ahead", { team: sides.home }),
      n: m.home_ahead,
    },
    { key: "level", label: tr("match.knowledge.story.level"), n: m.level },
    {
      key: "away",
      label: tr("match.knowledge.story.ahead", { team: sides.away }),
      n: m.away_ahead,
    },
  ];
  return (
    <EvidenceChart
      testId="score-state"
      title={t("matchviz.scoreState.title")}
      subtitle={t("matchviz.scoreState.subtitle")}
      evidence="E1"
      reading={{
        kind: "match",
        subject: t("matchviz.scoreState.subject", { home: sides.home, away: sides.away }),
        n: 1,
        source,
        minSample: 1,
      }}
      review={MATCH_BALANCE_REVIEW}
      method={t("matchviz.scoreState.method")}
      footer={t("matchviz.footer", { source, n: localInt(1) })}
    >
      <div className="space-y-3">
        <StoryBar drawing={state.drawing} sides={sides} />
        <table className="w-full border-collapse text-left text-sm" data-testid="score-state-table">
          <caption className="sr-only">{t("matchviz.scoreState.title")}</caption>
          <tbody>
            {spans.map((s) => (
              <tr
                key={s.key}
                data-state={s.key}
                className="border-b border-border/60 last:border-0"
              >
                <th scope="row" className="py-2 pr-2 font-normal text-muted-foreground">
                  {s.label}
                </th>
                <td className="numeric py-2 text-right font-semibold">
                  {tr("match.knowledge.minutes.short", { n: s.n })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {state.beyond90 ? (
          <p className="text-caption text-muted-foreground" data-testid="score-state-beyond90">
            {t("matchviz.scoreState.beyond90")}
          </p>
        ) : null}
      </div>
    </EvidenceChart>
  );
}
