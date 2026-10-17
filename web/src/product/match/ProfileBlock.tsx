/**
 * How the two teams come in (REVIEW PREDIGOL, point 5): results and average statistics over their newest
 * finished matches, in every competition or in this one. Each figure counts only the matches that carry its
 * data and says so when that is fewer than all of them; a figure no match carries reads "Sin dato" - never 0.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ListChecks } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import type { ProfileMetric, ProfileScope, ProfileValue } from "@/lib/api/v1/types_profile";
import { TeamName } from "@/components/football/Logos";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { profileText } from "./profile";
import { Block, SectionNote } from "./ui";

function Cell({
  m,
  v,
  matches,
  align,
  better,
}: {
  m: ProfileMetric;
  v: ProfileValue;
  matches: number;
  align: "left" | "right";
  better: boolean;
}) {
  const text = profileText(m, v);
  return (
    <div className={cn("min-w-0", align === "right" ? "text-right" : "text-left")}>
      <span
        className={cn(
          "numeric inline-block rounded-md px-1.5 py-0.5 text-sm",
          text === null
            ? "text-caption text-subtle-foreground"
            : better
              ? "bg-primary/12 font-semibold text-foreground"
              : "text-foreground/90",
        )}
      >
        {text ?? t("match.profile.noData")}
      </span>
      {text !== null && v.n < matches ? (
        <span className="block text-[0.65rem] leading-tight text-subtle-foreground">
          {t("match.profile.coverage", { n: v.n, total: matches })}
        </span>
      ) : null}
    </div>
  );
}

/** Which side reads better, for a light highlight only where "more" is plainly better or worse. */
const HIGHER_IS_BETTER = new Set([
  "wins",
  "win_or_draw",
  "clean_sheets",
  "ht_lead",
  "scored_first",
  "goals_for",
  "xg_for",
  "shots",
  "shots_on_target",
  "corners",
]);
const LOWER_IS_BETTER = new Set([
  "losses",
  "failed_to_score",
  "conceded_first",
  "goals_against",
  "xg_against",
  "shots_against",
  "corners_against",
]);

function better(m: ProfileMetric): "home" | "away" | null {
  const h = m.home.value === null ? null : Number(m.home.value);
  const a = m.away.value === null ? null : Number(m.away.value);
  if (h === null || a === null || h === a) return null;
  if (HIGHER_IS_BETTER.has(m.key)) return h > a ? "home" : "away";
  if (LOWER_IS_BETTER.has(m.key)) return h < a ? "home" : "away";
  return null;
}

function Table({ title, scope, kinds }: { title: string; scope: ProfileScope; kinds: string[] }) {
  const rows = scope.metrics.filter((m) => kinds.includes(m.kind));
  return (
    <div className="min-w-0">
      <h3 className="mb-1 text-label text-subtle-foreground">{title}</h3>
      <ul className="divide-y divide-border/60" data-testid={`profile-${kinds.join("-")}`}>
        {rows.map((m) => {
          const lead = better(m);
          return (
            <li
              key={m.key}
              data-metric={m.key}
              className="grid grid-cols-[minmax(4.5rem,auto)_minmax(0,1fr)_minmax(4.5rem,auto)] items-center gap-2 py-2"
            >
              <Cell
                m={m}
                v={m.home}
                matches={scope.home_matches}
                align="left"
                better={lead === "home"}
              />
              <span className="min-w-0 break-words text-center text-xs text-muted-foreground">
                {t(`match.profile.metric.${m.key}`)}
              </span>
              <Cell
                m={m}
                v={m.away}
                matches={scope.away_matches}
                align="right"
                better={lead === "away"}
              />
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function ProfileBlock({ ctx }: { ctx: MatchCtx }) {
  const q = useQuery(live.matchProfile(ctx.fixtureId));
  const [scopeName, setScopeName] = useState<"all" | "competition">("all");
  const profile = q.data?.data ?? null;
  const scope = profile?.scopes.find((s) => s.scope === scopeName) ?? profile?.scopes[0] ?? null;
  const { home, away } = ctx.match;
  const choices: Array<{ key: "all" | "competition"; label: string }> = [
    { key: "all", label: t("match.profile.scopeAll") },
    {
      key: "competition",
      label: ctx.match.competition.name || t("match.profile.scopeCompetition"),
    },
  ];
  return (
    <Block title={t("match.profile.title")} icon={<ListChecks />}>
      {q.isPending ? (
        <SkeletonBlock className="h-72" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-5" />
      ) : !scope || q.data?.status !== "ok" ? (
        <SectionNote status="empty">{t("match.profile.none")}</SectionNote>
      ) : (
        <div className="space-y-4" data-testid="match-profile">
          <div
            role="radiogroup"
            aria-label={t("match.profile.title")}
            className="inline-flex max-w-full flex-wrap gap-1 rounded-lg border border-border bg-background/40 p-1"
          >
            {choices.map((c) => (
              <button
                key={c.key}
                type="button"
                role="radio"
                aria-checked={scopeName === c.key}
                onClick={() => setScopeName(c.key)}
                className={cn(
                  "min-h-8 rounded-md px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                  scopeName === c.key
                    ? "bg-elevated text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {c.label}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-2 gap-3 text-xs">
            <div className="min-w-0">
              <TeamName name={home.name} logo={home.logo_url} size={18} strong />
              <span className="mt-0.5 block text-caption text-subtle-foreground">
                {t("match.profile.lastN", { count: scope.home_matches })}
              </span>
            </div>
            <div className="min-w-0 text-right">
              <TeamName
                name={away.name}
                logo={away.logo_url}
                size={18}
                strong
                reverse
                className="justify-end"
              />
              <span className="mt-0.5 block text-caption text-subtle-foreground">
                {t("match.profile.lastN", { count: scope.away_matches })}
              </span>
            </div>
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Table title={t("match.profile.results")} scope={scope} kinds={["count"]} />
            <Table title={t("match.profile.averages")} scope={scope} kinds={["average", "ratio"]} />
          </div>
          <p className="text-caption text-subtle-foreground">{t("match.profile.note")}</p>
        </div>
      )}
    </Block>
  );
}
