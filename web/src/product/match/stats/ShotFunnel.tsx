/**
 * «Embudo de remate» and «Zona de remate · 2 zonas» (plan PM, PM-10-01, OP-22, lámina I01 «M01»; FE-005): what a team made of its
 * shots, and where it took them from - inside or outside the box, the provider's only two zones. Drawn only with
 * `FBI_MATCH_SHOT_FUNNEL` on and team statistics of level B or better (the page decides: `StatsTab`).
 *
 * Each card is an `EvidenceChart` (PM-10-06): its level (E1, descriptive: one match), its reading sentence with the sample (one
 * match) and the origin, its «ficha» and a table with the same figures one tap away. The bars are the system's `StatBars`; the two
 * zones are a box inside a box, the inner one the area. «2 zonas» is in the title: it is not a shot map.
 */
import type { ReactNode } from "react";
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import { TeamName } from "@/components/football/Logos";
import type { Side } from "@/lib/api/v1/types_center";
import { localInt } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { fmtDecimal, type StatRow } from "../model";
import { StatBars, TeamsLegend } from "../ui";
import { t } from "./matchvizText";
import {
  SHOT_FUNNEL_REVIEW,
  share,
  xgPerShot,
  type ShotFunnel as Funnel,
  type ShotZones,
} from "./shots";

export interface FunnelTeams {
  home: { name: string; logo_url?: string | null | undefined };
  away: { name: string; logo_url?: string | null | undefined };
}

function pctText(v: number | null): string | null {
  return v === null ? null : `${localInt(v)} %`;
}

/** The same figures as a table, folded: the chart's equivalent for a screen reader, a keyboard or a copy. */
export function EquivalentTable({
  caption,
  teams,
  rows,
}: {
  caption: string;
  teams: FunnelTeams;
  rows: { key: string; label: string; home: string; away: string }[];
}) {
  return (
    <details className="group text-caption">
      <summary className="inline-flex min-h-11 cursor-pointer list-none items-center rounded-md px-1 font-medium text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        {t("matchviz.table.show")}
      </summary>
      <table className="mt-1 w-full border-collapse text-left text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-border text-muted-foreground">
            <th scope="col" className="py-1.5 pr-2 font-medium">
              {t("matchviz.table.datum")}
            </th>
            <th scope="col" className="py-1.5 pr-2 text-right font-medium">
              {teams.home.name}
            </th>
            <th scope="col" className="py-1.5 text-right font-medium">
              {teams.away.name}
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} data-row={r.key} className="border-b border-border/60 last:border-0">
              <th scope="row" className="py-1.5 pr-2 font-normal text-muted-foreground">
                {r.label}
              </th>
              <td className="numeric py-1.5 pr-2 text-right">{r.home}</td>
              <td className="numeric py-1.5 text-right">{r.away}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

function withPct(value: number, whole: number): string {
  const p = share(value, whole);
  return p === null ? localInt(value) : `${localInt(value)} (${localInt(p)} %)`;
}

/** «Embudo de remate»: shots, on target and goals of each side, each step against the side's own shots. */
export function ShotFunnelCard({
  funnel,
  teams,
  source,
}: {
  funnel: Funnel;
  teams: FunnelTeams;
  source: string;
}) {
  const steps = [
    { key: "shots", home: funnel.home.shots, away: funnel.away.shots },
    { key: "onTarget", home: funnel.home.onTarget, away: funnel.away.onTarget },
    { key: "goals", home: funnel.home.goals, away: funnel.away.goals },
  ] as const;
  const rows: StatRow[] = steps.map((s) => ({
    key: s.key,
    format: "int",
    home: s.home,
    away: s.away,
  }));
  const whole = (side: Side) => funnel[side].shots;
  const own = funnel.ownGoals.home + funnel.ownGoals.away;
  const aria = (side: Side) =>
    t("matchviz.funnel.aria", {
      team: teams[side].name,
      shots: localInt(funnel[side].shots),
      onTarget: localInt(funnel[side].onTarget),
      goals: localInt(funnel[side].goals),
    });
  return (
    <EvidenceChart
      testId="shot-funnel"
      title={t("matchviz.funnel.title")}
      subtitle={t("matchviz.funnel.subtitle")}
      evidence="E1"
      reading={{
        kind: "match",
        subject: t("matchviz.funnel.subject", { home: teams.home.name, away: teams.away.name }),
        n: 1,
        source,
        minSample: 1,
      }}
      review={SHOT_FUNNEL_REVIEW}
      method={t("matchviz.funnel.method")}
      footer={t("matchviz.footer", { source, n: localInt(1) })}
    >
      <div className="space-y-4">
        <TeamsLegend home={teams.home} away={teams.away} />
        <ul className="sr-only">
          <li>{aria("home")}</li>
          <li>{aria("away")}</li>
        </ul>
        <div aria-hidden>
          <StatBars
            rows={rows}
            labelOf={(r) => t(`matchviz.funnel.${r.key}`)}
            widthOf={(r, side) => share(r[side] ?? 0, whole(side)) ?? 0}
            noteOf={(r, side) => pctText(share(r[side] ?? 0, whole(side)))}
          />
        </div>
        <p className="text-caption text-muted-foreground">{t("matchviz.funnel.note")}</p>
        {own > 0 ? (
          <p className="text-caption text-muted-foreground" data-testid="shot-funnel-own-goals">
            {t("matchviz.funnel.ownGoals", { count: localInt(own) })}
          </p>
        ) : null}
        {funnel.goalsFrom === "score" ? (
          <p className="text-caption text-muted-foreground" data-testid="shot-funnel-from-score">
            {t("matchviz.funnel.goalsFromScore")}
          </p>
        ) : null}
        <EquivalentTable
          caption={t("matchviz.funnel.title")}
          teams={teams}
          rows={steps.map((s) => ({
            key: s.key,
            label: t(`matchviz.funnel.${s.key}`),
            home: withPct(s.home, whole("home")),
            away: withPct(s.away, whole("away")),
          }))}
        />
      </div>
    </EvidenceChart>
  );
}

/** One side's two zones: the area as an inner box (inside), the rest around it (outside). */
function ZoneBox({
  side,
  team,
  inside,
  outside,
}: {
  side: Side;
  team: FunnelTeams["home"];
  inside: number;
  outside: number;
}) {
  const total = inside + outside;
  const inPct = share(inside, total);
  const outPct = share(outside, total);
  const insideLeads = inside >= outside;
  return (
    <div
      data-side={side}
      className="min-w-0 space-y-2 rounded-xl border border-border bg-elevated/30 p-3"
    >
      <TeamName
        name={team.name}
        logo={team.logo_url}
        size={18}
        strong
        wrap
        className="min-w-0 text-xs"
      />
      <p className="sr-only">
        {t("matchviz.zones.aria", {
          team: team.name,
          inside: localInt(inside),
          insidePct: localInt(inPct ?? 0),
          outside: localInt(outside),
          outsidePct: localInt(outPct ?? 0),
        })}
      </p>
      <div aria-hidden className="rounded-lg border border-border-strong px-2 pb-2 pt-0">
        <div
          className={cn(
            "mx-auto -mt-px w-4/5 rounded-b-md border px-2 py-2 text-center",
            side === "home" ? "border-primary/70 bg-primary/12" : "border-info/70 bg-info-soft",
            insideLeads ? "border-2" : "border",
          )}
        >
          <span className="numeric block text-lg font-bold leading-tight">{localInt(inside)}</span>
          <span className="block text-caption text-foreground-soft">
            {t("matchviz.zones.inside")}
            {/* the figure and its sign never split across lines (PM-14-11: «56» / «%» at 390 px) */}
            {inPct === null ? "" : ` · ${localInt(inPct)}\u00a0%`}
          </span>
        </div>
        <div className="pt-2 text-center">
          <span className="numeric block text-lg font-bold leading-tight">{localInt(outside)}</span>
          <span className="block text-caption text-foreground-soft">
            {t("matchviz.zones.outside")}
            {outPct === null ? "" : ` · ${localInt(outPct)}\u00a0%`}
          </span>
        </div>
      </div>
    </div>
  );
}

function FigureRow({ label, home, away }: { label: string; home: string; away: string }) {
  return (
    <li className="flex items-baseline justify-between gap-2 border-b border-border/60 py-2 last:border-0">
      <span className="numeric w-14 shrink-0 text-sm font-semibold">{home}</span>
      <span className="min-w-0 text-center text-[0.8125rem] text-muted-foreground">{label}</span>
      <span className="numeric w-14 shrink-0 text-right text-sm font-semibold">{away}</span>
    </li>
  );
}

/** «Zona de remate · 2 zonas»: inside and outside the box per side, with blocked shots and xG where the provider gave them. */
export function ShotZonesCard({
  zones,
  teams,
  source,
  shots,
}: {
  zones: ShotZones;
  teams: FunnelTeams;
  source: string;
  /** The sides' shots, for xG per shot (from the funnel when it is drawn). */
  shots?: { home: number; away: number } | undefined;
}) {
  const { home, away } = zones;
  const blocked = home.blocked !== null && away.blocked !== null;
  const xg = home.xg !== null && away.xg !== null;
  const total = (s: "home" | "away") => shots?.[s] ?? zones[s].inside + zones[s].outside;
  const perShot = (s: "home" | "away") => xgPerShot(zones[s].xg, total(s));
  const figures: { key: string; label: string; home: string; away: string }[] = [];
  if (blocked)
    figures.push({
      key: "blocked",
      label: t("matchviz.zones.blocked"),
      home: localInt(home.blocked ?? 0),
      away: localInt(away.blocked ?? 0),
    });
  if (xg) {
    figures.push({
      key: "xg",
      label: t("matchviz.zones.xg"),
      home: fmtDecimal(home.xg, 2),
      away: fmtDecimal(away.xg, 2),
    });
    const ph = perShot("home");
    const pa = perShot("away");
    if (ph !== null && pa !== null)
      figures.push({
        key: "xgPerShot",
        label: t("matchviz.zones.xgPerShot"),
        home: fmtDecimal(ph, 2),
        away: fmtDecimal(pa, 2),
      });
  }
  const zoneRows = (["inside", "outside"] as const).map((z) => ({
    key: z,
    label: t(z === "inside" ? "matchviz.zones.insideLong" : "matchviz.zones.outsideLong"),
    home: withPct(home[z], home.inside + home.outside),
    away: withPct(away[z], away.inside + away.outside),
  }));
  const extra: ReactNode =
    figures.length > 0 ? (
      <ul className="rounded-xl border border-border px-3" data-testid="shot-zones-figures">
        {figures.map((f) => (
          <FigureRow key={f.key} label={f.label} home={f.home} away={f.away} />
        ))}
      </ul>
    ) : null;
  return (
    <EvidenceChart
      testId="shot-zones"
      title={t("matchviz.zones.title")}
      subtitle={t("matchviz.zones.subtitle")}
      evidence="E1"
      reading={{
        kind: "match",
        subject: t("matchviz.zones.subject", { home: teams.home.name, away: teams.away.name }),
        n: 1,
        source,
        minSample: 1,
      }}
      review={SHOT_FUNNEL_REVIEW}
      method={t("matchviz.zones.method")}
      footer={t("matchviz.footer", { source, n: localInt(1) })}
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <ZoneBox side="home" team={teams.home} inside={home.inside} outside={home.outside} />
          <ZoneBox side="away" team={teams.away} inside={away.inside} outside={away.outside} />
        </div>
        {extra}
        <p className="text-caption text-muted-foreground" data-testid="shot-zones-honest">
          {t("matchviz.zones.honest")}
          {xg ? ` ${t("matchviz.zones.xgSource")}` : ""}
        </p>
        <EquivalentTable
          caption={t("matchviz.zones.title")}
          teams={teams}
          rows={[...zoneRows, ...figures]}
        />
      </div>
    </EvidenceChart>
  );
}
