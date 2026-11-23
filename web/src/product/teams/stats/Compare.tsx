/**
 * The comparisons (plan EA, EA-104 and EA-105; maquetas V2·3 and V2·4): two teams on the six fixed axes (radar or bars, the same
 * numbers), their percentiles and game states side by side, each against its own league; two players on the same distributions of
 * their position, and volume against accuracy over the league's players. No single score, no «rating».
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import { isMissing, present } from "@/lib/api/v1/types_intelligence";
import type { StatsEntity, StatsScope, StatsContext } from "@/lib/api/v1/types_stats";
import { useStatsSwitches } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { EvidenceChart } from "@/components/analytics/EvidenceChart";
import { READER_REVIEW } from "@/components/analytics/readerReview";
import { ChartCard, ChipChoice } from "@/components/analytics/stats/ChartCard";
import {
  compareRadarReading,
  comparePlayersReading,
  figurePlace,
  scatterReading,
} from "@/components/analytics/stats/howToRead";
import { t as r } from "@/components/analytics/stats/readText";
import { RadarBars } from "@/components/analytics/stats/RadarBars";
import { DistributionRow } from "@/components/analytics/stats/PositionDistribution";
import { VolumeAccuracy } from "@/components/analytics/stats/SmallCharts";
import { figName, figValue } from "@/components/analytics/stats/format";
import { teamColor } from "./shared";

type Kind = "teams" | "players";

function Picker({
  kind,
  label,
  onPick,
}: {
  kind: Kind;
  label: string;
  onPick: (id: number) => void;
}) {
  const [term, setTerm] = useState("");
  const teams = useQuery({
    ...live.teamSearch(term),
    enabled: kind === "teams" && term.length >= 2,
  });
  const players = useQuery({
    ...live.players({ q: term }),
    enabled: kind === "players" && term.length >= 2,
  });
  const items =
    kind === "teams"
      ? (teams.data?.data ?? []).map((x) => ({ id: x.id, name: x.name, sub: x.country }))
      : (players.data?.data ?? []).map((x) => ({ id: x.id, name: x.name, sub: x.team }));
  return (
    <div className="space-y-2">
      <label className="block text-small text-muted-foreground">
        {label}
        <input
          type="search"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          className="mt-1 block min-h-11 w-full rounded-xl border border-border bg-elevated px-3 text-sm text-foreground"
          placeholder={kind === "teams" ? t("stats.compareSearch") : t("stats.compareSearchPlayer")}
        />
      </label>
      {items.length ? (
        <ul className="max-h-64 overflow-y-auto rounded-xl border border-border">
          {items.slice(0, 12).map((x) => (
            <li key={x.id}>
              <button
                type="button"
                onClick={() => onPick(x.id)}
                className="flex min-h-11 w-full items-center justify-between gap-2 px-3 text-left text-sm hover:bg-elevated"
              >
                <span className="truncate font-semibold">{x.name}</span>
                <span className="truncate text-small text-subtle-foreground">{x.sub ?? ""}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function Head({ entities }: { entities: StatsEntity[] }) {
  return (
    <div className="flex items-center justify-center gap-3 text-center">
      {entities.map((e, i) => (
        <div key={e.role} className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <span className="h-3 w-3 rounded-full" style={{ background: teamColor(i) }} aria-hidden />
          <span className="truncate text-sm font-semibold">
            {present(e.team)?.team.name ?? present(e.player)?.player.name ?? "—"}
          </span>
          <span className="text-small text-subtle-foreground">
            {e.competition.competition.name} {e.competition.season}
          </span>
        </div>
      ))}
    </div>
  );
}

function TeamsBody({ entities }: { entities: StatsEntity[] }) {
  const bodies = entities.map((e) => present(e.team));
  if (bodies.some((b) => !b)) return null;
  const [a, b] = bodies as [NonNullable<(typeof bodies)[0]>, NonNullable<(typeof bodies)[0]>];
  const statesOf = (x: typeof a) => present(x.states);
  const first = (x: typeof a) => x.trends.items.find((r) => r.key === "scores_first");
  const pctLeading = (x: typeof a) => {
    const s = statesOf(x);
    if (!s) return "—";
    const total = s.minutes_leading + s.minutes_level + s.minutes_trailing;
    return `${Math.round((100 * s.minutes_leading) / Math.max(1, total))} %`;
  };
  const rows: [string, string, string][] = [
    [
      t("stats.pointsRescued"),
      String(statesOf(a)?.points_rescued ?? "—"),
      String(statesOf(b)?.points_rescued ?? "—"),
    ],
    [t("stats.minutesLeading"), pctLeading(a), pctLeading(b)],
    [
      t("stats.trend.scores_first"),
      first(a) ? `${first(a)!.hits}/${first(a)!.n}` : "—",
      first(b) ? `${first(b)!.hits}/${first(b)!.n}` : "—",
    ],
  ];
  const keys = a.figures.map((f) => f.key);
  const common = { evidence: "E1", review: READER_REVIEW } as const;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <EvidenceChart
        {...common}
        title={r("readchart.compareRadar.title")}
        axes={r("readchart.radar.axis")}
        reading={compareRadarReading(
          { name: a.team.name, axes: a.radar },
          { name: b.team.name, axes: b.radar },
          Math.min(a.record.matches, b.record.matches),
        )}
        terms={["percentile"]}
        footer={r("readchart.radar.how")}
        testId="compare-radar"
      >
        <RadarBars
          sides={[
            { name: a.team.name, axes: a.radar, color: teamColor(0) },
            { name: b.team.name, axes: b.radar, color: teamColor(1) },
          ]}
        />
      </EvidenceChart>
      <div className="flex flex-col gap-4">
        <ChartCard title={t("stats.compareStates")} testId="compare-states">
          <dl className="grid gap-2">
            {rows.map(([label, x, y]) => (
              <div
                key={label}
                className="flex items-center justify-between gap-2 rounded-xl bg-elevated px-3 py-2 text-sm"
              >
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="numeric font-semibold">
                  {x} · {y}
                </dd>
              </div>
            ))}
          </dl>
        </ChartCard>
        <ChartCard
          title={t("stats.performance")}
          subtitle={t("stats.compareEach")}
          testId="compare-figures"
        >
          <ul className="space-y-1.5 text-small">
            {keys.map((k) => {
              const fa = a.figures.find((f) => f.key === k)!;
              const fb = b.figures.find((f) => f.key === k);
              return (
                <li key={k} className="grid grid-cols-[minmax(0,1fr)_auto_auto] gap-3">
                  <span className="truncate text-foreground-soft">{figName(k)}</span>
                  <span className="numeric" style={{ color: teamColor(0) }}>
                    {figValue(fa)}{" "}
                    <span className="text-subtle-foreground">{figurePlace(fa) ?? "—"}</span>
                  </span>
                  <span className="numeric" style={{ color: teamColor(1) }}>
                    {fb ? figValue(fb) : "—"}{" "}
                    <span className="text-subtle-foreground">
                      {fb ? (figurePlace(fb) ?? "—") : ""}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </ChartCard>
      </div>
    </div>
  );
}

function PlayersBody({ entities }: { entities: StatsEntity[] }) {
  const bodies = entities.map((e) => present(e.player));
  if (bodies.some((b) => !b)) return null;
  const [a, b] = bodies as [NonNullable<(typeof bodies)[0]>, NonNullable<(typeof bodies)[0]>];
  const position = present(a.position);
  const scatter = present(entities[0]!.scatter) ?? [];
  const point = (id: number) =>
    scatter.find((p) => p.player_id === id) ??
    present(entities[1]!.scatter)?.find((p) => p.player_id === id) ??
    null;
  const common = { evidence: "E1", review: READER_REVIEW } as const;
  const pa = { name: a.player.name, point: point(a.player.id), color: teamColor(0) };
  const pb = { name: b.player.name, point: point(b.player.id), color: teamColor(1) };
  const scatterRead = scatterReading(
    pa,
    pb,
    Math.floor(Math.min(a.nineties, b.nineties)),
    Math.ceil(Math.max(a.min_nineties, b.min_nineties)),
  );
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <EvidenceChart
        {...common}
        title={r("readchart.comparePlayers.title")}
        axes={r("readchart.comparePlayers.axis")}
        reading={comparePlayersReading(a, b)}
        terms={["percentile"]}
        testId="compare-distributions"
      >
        <p className="text-small text-subtle-foreground">
          {a.player.name}: {t("stats.sampleNineties", { n: localFixed(a.nineties, 1) })} ·{" "}
          {b.player.name}: {t("stats.sampleNineties", { n: localFixed(b.nineties, 1) })}
        </p>
        <div className="space-y-3">
          {a.figures.map((fa) => {
            const fb = b.figures.find((f) => f.key === fa.key);
            return (
              <DistributionRow
                key={fa.key}
                players={[
                  { name: a.player.name, figure: fa, color: teamColor(0) },
                  ...(fb && !isMissing(fb.value)
                    ? [{ name: b.player.name, figure: fb, color: teamColor(1) }]
                    : []),
                ]}
              />
            );
          })}
        </div>
      </EvidenceChart>
      {scatterRead ? (
        <EvidenceChart
          {...common}
          title={r("readchart.scatter.title")}
          axes={r("readchart.scatter.axis")}
          reading={scatterRead}
          testId="compare-scatter"
        >
          <VolumeAccuracy background={scatter} players={[pa, pb]} />
        </EvidenceChart>
      ) : (
        <ChartCard title={r("readchart.scatter.title")} testId="compare-scatter">
          <p className="text-small text-subtle-foreground">{t("stats.missing.sin_datos")}</p>
        </ChartCard>
      )}
    </div>
  );
}

export function ComparePage({
  kind,
  a,
  b,
}: {
  kind: Kind;
  a?: number | undefined;
  b?: number | undefined;
}) {
  const { stats: open } = useStatsSwitches();
  const navigate = useNavigate();
  const [scope, setScope] = useState<StatsScope>("season");
  const [context, setContext] = useState<StatsContext>("all");
  const ready = open && a !== undefined && b !== undefined && a !== b;
  const teams = useQuery({
    ...live.compareTeams(a ?? 0, b ?? 0, { scope, context }),
    enabled: ready && kind === "teams",
  });
  const players = useQuery({
    ...live.comparePlayers(a ?? 0, b ?? 0),
    enabled: ready && kind === "players",
  });
  const q = kind === "teams" ? teams : players;
  const pick = (side: "a" | "b") => (id: number) =>
    void navigate({
      to: ".",
      search: { a: side === "a" ? id : a, b: side === "b" ? id : b } as never,
      replace: true,
    });
  if (!open)
    return (
      <Card className="p-4">
        <EmptyState title={t("stats.closed")} />
      </Card>
    );
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-4" data-testid={`compare-${kind}`}>
      <h1 className="text-heading">
        {kind === "teams" ? t("stats.compareTeams") : t("stats.comparePlayers")}
      </h1>
      {!ready ? (
        <Card className="grid gap-4 p-4 sm:grid-cols-2">
          {a === undefined ? (
            <Picker kind={kind} label={t("stats.comparePick")} onPick={pick("a")} />
          ) : null}
          {b === undefined || a === b ? (
            <Picker kind={kind} label={t("stats.comparePick")} onPick={pick("b")} />
          ) : null}
          {a !== undefined && a === b ? (
            <p className="text-small text-warning">{t("stats.compareSame")}</p>
          ) : null}
        </Card>
      ) : null}
      {ready && kind === "teams" ? (
        <div className="flex flex-col gap-2 sm:flex-row">
          <ChipChoice
            value={scope}
            onChange={setScope}
            label={t("stats.scopeLabel")}
            options={(["u5", "u10", "u20", "season"] as const).map((s) => ({
              value: s,
              label: t(`stats.scope.${s}`),
            }))}
          />
          <ChipChoice
            value={context}
            onChange={setContext}
            label={t("stats.contextLabel")}
            options={(["all", "home", "away"] as const).map((c) => ({
              value: c,
              label: t(`stats.context.${c}`),
            }))}
          />
        </div>
      ) : null}
      {ready && q.isPending ? <SkeletonCards count={2} /> : null}
      {ready && q.isError ? (
        <Card className="p-4">
          {q.error instanceof LiveApiError && q.error.status === 404 ? (
            <EmptyState title={kind === "teams" ? t("stats.none") : t("stats.nonePlayer")} />
          ) : (
            <ErrorState error={q.error} onRetry={() => void q.refetch()} />
          )}
        </Card>
      ) : null}
      {ready && q.data ? (
        <>
          <Card className="p-4">
            <Head entities={q.data.data.entities} />
          </Card>
          {kind === "teams" ? (
            <TeamsBody entities={q.data.data.entities} />
          ) : (
            <PlayersBody entities={q.data.data.entities} />
          )}
          <p className="text-center text-small text-subtle-foreground">
            {kind === "teams" ? t("stats.radarSame") : t("stats.playerNote")}
          </p>
        </>
      ) : null}
    </div>
  );
}
