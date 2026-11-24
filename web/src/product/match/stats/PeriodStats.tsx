/**
 * «Estadísticas por mitad» (plan PM, PM-10-03, OP-06; FE-010): the match, the first half and the second half of the statistics the
 * competition delivers by half, in the Match Center's Estadísticas once the match is under way. Drawn only with `FBI_MATCH_HALVES` on
 * (`MatchVizSection` decides). Reuses the system's pieces: `EvidenceChart` (E1: one match, its sentence, its method and the same
 * figures as a table), `StatBars`, the segmented control, and the shared «información no disponible» (UX-173) for the two ways it can
 * be absent: the competition does not deliver the halves (the section is one line, no card) and this match's halves have not come
 * yet (a pending card). It also stays quiet while the answer is loading or fails: never an empty card, never a zero.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import { Segmented } from "@/components/ui/segmented";
import { live } from "@/lib/api/v1/queries";
import type { MatchPeriodStats, PeriodKey } from "@/lib/api/v1/types_period_stats";
import { t as tr } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { NotOffered, PendingData } from "@/product/shared/Unavailable";
import type { ChartReview } from "@/components/analytics/evidence";
import { fmtStat } from "../model";
import { StatBars, TeamsLegend } from "../ui";
import { t } from "./matchvizText";
import { halvesAddUp, periodRows, periodsWithRows } from "./periods";
import { EquivalentTable, type FunnelTeams } from "./ShotFunnel";

/** The review of the 14 checks (PM-10-06) by the author, from the pieces it is made of; the visual QA of the owner is still to come. */
export const MATCH_PERIODS_REVIEW: ChartReview = {
  checks: {
    contraste: "ok",
    alternativa_textual: "ok",
    texto_minimo: "ok",
    sin_parpadeo: "ok",
    color_no_unico: "ok",
    teclado: "ok",
    foco_visible: "ok",
    instrucciones: "no_aplica",
    titulo_y_resumen: "ok",
    incertidumbre: "ok",
    lenguaje_llano: "ok",
    tabla_equivalente: "ok",
    zoom_y_espaciado: "ok",
    lector_de_pantalla: "ok",
  },
  reviewedBy: "FE-010",
  reviewedOn: "2026-11-24",
};

const LABEL: Record<PeriodKey, string> = { total: "total", "1h": "h1", "2h": "h2" };

/** The card, for an answer that has figures. */
export function PeriodStatsCard({
  data,
  teams,
  source,
}: {
  data: MatchPeriodStats;
  teams: FunnelTeams;
  source: string;
}) {
  const available = periodsWithRows(data);
  const [chosen, setChosen] = useState<PeriodKey>("total");
  const period = available.includes(chosen) ? chosen : (available[0] ?? "total");
  const rows = periodRows(data, period);
  const name = t(`matchviz.periods.${LABEL[period]}`);
  const label = (r: { key: string }) => tr(`match.stats.label.${r.key}`);
  return (
    <EvidenceChart
      testId="match-periods"
      title={t("matchviz.periods.title")}
      subtitle={t("matchviz.periods.subtitle")}
      evidence="E1"
      reading={{
        kind: "match",
        subject: t("matchviz.periods.subject", { home: teams.home.name, away: teams.away.name }),
        n: 1,
        source,
        minSample: 1,
      }}
      review={MATCH_PERIODS_REVIEW}
      method={t("matchviz.periods.method")}
      footer={t("matchviz.footer", { source, n: localInt(1) })}
    >
      <div className="space-y-4">
        <Segmented<PeriodKey>
          value={period}
          onChange={setChosen}
          label={t("matchviz.periods.choose")}
          testId="match-periods-switch"
          options={available.map((p) => ({ value: p, label: t(`matchviz.periods.${LABEL[p]}`) }))}
        />
        <TeamsLegend home={teams.home} away={teams.away} />
        <ul className="sr-only">
          {rows.map((r) => (
            <li key={r.key}>
              {t("matchviz.periods.aria", {
                label: label(r),
                period: name,
                home: teams.home.name,
                homeValue: fmtStat(r.home, r.format),
                away: teams.away.name,
                awayValue: fmtStat(r.away, r.format),
              })}
            </li>
          ))}
        </ul>
        <div aria-hidden data-period={period}>
          <StatBars rows={rows} />
        </div>
        <p className="text-caption text-muted-foreground">
          {halvesAddUp(data) ? t("matchviz.periods.note") : t("matchviz.periods.noMatch")}
        </p>
        <EquivalentTable
          caption={`${t("matchviz.periods.title")} · ${name}`}
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

/**
 * The piece `MatchVizSection` mounts: reads the answer and draws the card, the one line of a competition that does not deliver the
 * halves, or the pending card of a match whose halves have not come. While loading, on an error or on a 404 it draws nothing.
 */
export function PeriodStats({ fixtureId, teams }: { fixtureId: string; teams: FunnelTeams }) {
  const q = useQuery({ ...live.matchPeriodStats(fixtureId), retry: false });
  const answer = q.data;
  if (!answer) return null;
  const data = answer.data;
  const source = t("matchviz.periods.source");
  if (answer.status === "ok" && periodsWithRows(data).length > 0) {
    return <PeriodStatsCard data={data} teams={teams} source={source} />;
  }
  if (answer.reason === "partido_sin_mitades") {
    return (
      <PendingData
        subject={t("matchviz.periods.subjectPending")}
        step="existe"
        className="lg:col-span-2"
      />
    );
  }
  if (answer.reason === "sin_estadisticas_por_mitad") {
    return <NotOffered subjects={[t("matchviz.periods.subjectNone")]} className="lg:col-span-2" />;
  }
  return null;
}
