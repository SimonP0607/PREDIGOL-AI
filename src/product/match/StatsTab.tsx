/** Every team figure we have for the match side by side, and the best-rated players. */
import { useState } from "react";
import { BarChart3, Star, Trophy } from "lucide-react";
import { t, translateOr } from "@/lib/i18n";
import { toNumber } from "@/lib/i18n/format";
import type { PlayerLine } from "@/lib/api/v1/types_center";
import { PlayerPhoto, TeamLogo } from "@/components/football/Logos";
import type { MatchCtx } from "./context";
import { ageLevel, notPlayed, ratedPlayers, seasonRows, statRows } from "./model";
import { ProfileBlock } from "./ProfileBlock";
import {
  Block,
  CenterSection,
  FreshnessLabel,
  MoreButton,
  PlayerName,
  RatingBadge,
  SectionNote,
  StatBars,
  TeamsLegend,
} from "./ui";

function PlayerFacts({ p }: { p: PlayerLine }) {
  const facts = [
    p.position_played
      ? translateOr(`match.lineups.position.${p.position_played}`, p.position_played)
      : null,
    p.minutes !== null ? t("match.players.minutes", { count: p.minutes }) : null,
    p.goals ? t("match.players.goals", { count: p.goals }) : null,
    p.assists ? t("match.players.assists", { count: p.assists }) : null,
    p.saves ? t("match.players.saves", { count: p.saves }) : null,
    p.key_passes ? t("match.players.keyPasses", { count: p.key_passes }) : null,
  ].filter((x): x is string => x !== null);
  return <span>{facts.join(" · ")}</span>;
}

function TopPlayers({ ctx, players }: { ctx: MatchCtx; players: PlayerLine[] }) {
  const [all, setAll] = useState(false);
  const rated = ratedPlayers(players);
  if (rated.length === 0) return <SectionNote>{t("match.players.none")}</SectionNote>;
  const shown = all ? rated : rated.slice(0, 5);
  return (
    <div>
      <ol className="divide-y divide-border/60">
        {shown.map((p, i) => {
          const team = p.side === "home" ? ctx.match.home : ctx.match.away;
          const rating = toNumber(p.rating) ?? 0;
          return (
            <li key={p.provider_player_id} className="flex items-center gap-3 py-2">
              <span className="numeric w-4 shrink-0 text-right text-caption text-subtle-foreground">
                {i + 1}
              </span>
              <span className="relative shrink-0">
                <PlayerPhoto src={p.photo_url} name={p.name ?? "?"} size={30} />
                <TeamLogo
                  src={team.logo_url}
                  name={team.name}
                  size={14}
                  className="absolute -bottom-1 -right-1"
                />
              </span>
              <div className="min-w-0 flex-1">
                <PlayerName
                  name={p.name}
                  id={p.player_id}
                  admin={ctx.showAdmin}
                  className="block truncate text-sm font-medium"
                />
                <div className="truncate text-caption text-muted-foreground">
                  <PlayerFacts p={p} />
                </div>
              </div>
              {i === 0 ? <span className="sr-only">{t("match.players.best")}</span> : null}
              <RatingBadge value={rating} top={i === 0} />
            </li>
          );
        })}
      </ol>
      {rated.length > 5 ? (
        <MoreButton expanded={all} onClick={() => setAll((v) => !v)} className="mt-1">
          {all ? t("match.players.showLess") : t("match.players.showAll", { count: rated.length })}
        </MoreButton>
      ) : null}
    </div>
  );
}

function TopPlayersBlock({ ctx }: { ctx: MatchCtx }) {
  return (
    <Block title={t("match.players.title")} icon={<Star />}>
      <CenterSection center={ctx.center} pick={(c) => c.players}>
        {(players) => <TopPlayers ctx={ctx} players={players} />}
      </CenterSection>
    </Block>
  );
}

/**
 * Before kick-off (REVIEW PREDIGOL, point 5): how the two teams come in - every result and average we hold, by
 * coverage - then the season from the league table.
 */
function PreMatchStats({ ctx }: { ctx: MatchCtx }) {
  const { home, away } = ctx.match;
  return (
    <div className="space-y-4">
      <SectionNote>{t("match.stats.notStarted")}</SectionNote>
      <ProfileBlock ctx={ctx} />
      <Block title={t("match.stats.season")} icon={<Trophy />}>
        <CenterSection center={ctx.center} pick={(c) => c.standings}>
          {(rows) => {
            const h = rows.find((r) => r.side === "home");
            const a = rows.find((r) => r.side === "away");
            const bars = seasonRows(h, a);
            if (bars.length === 0) return <SectionNote />;
            return (
              <div className="space-y-4">
                <TeamsLegend home={home} away={away} />
                {h?.table || a?.table ? (
                  <p className="-mt-2 text-caption text-subtle-foreground">
                    {t("match.standings.tableOf", {
                      table: [...new Set([h?.table, a?.table].filter(Boolean))].join(" · "),
                    })}
                  </p>
                ) : null}
                <p className="numeric -mt-2 flex justify-between text-caption text-muted-foreground">
                  <span>{h ? t("match.stats.position", { rank: h.rank }) : ""}</span>
                  <span>{a ? t("match.stats.position", { rank: a.rank }) : ""}</span>
                </p>
                <StatBars rows={bars} />
              </div>
            );
          }}
        </CenterSection>
      </Block>
    </div>
  );
}

export function StatsTab({ ctx }: { ctx: MatchCtx }) {
  if (ctx.phase === "scheduled" || notPlayed(ctx.phase)) {
    return <PreMatchStats ctx={ctx} />;
  }
  const { home, away } = ctx.match;
  const lines = ctx.center.data?.statistics.status === "ok" ? ctx.center.data.statistics.data : [];
  const at = lines[0]?.fetched_at ?? null;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
      <Block
        title={t("match.stats.title")}
        icon={<BarChart3 />}
        right={
          at && ctx.phase === "live" ? <FreshnessLabel at={at} level={ageLevel(at, 3, 10)} /> : null
        }
      >
        <CenterSection center={ctx.center} pick={(c) => c.statistics}>
          {(data) => (
            <div className="space-y-4">
              <TeamsLegend home={home} away={away} />
              <StatBars rows={statRows(data)} />
            </div>
          )}
        </CenterSection>
      </Block>
      <TopPlayersBlock ctx={ctx} />
    </div>
  );
}
