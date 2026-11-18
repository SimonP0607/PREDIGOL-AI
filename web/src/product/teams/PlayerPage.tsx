/**
 * The profile of a player (plan maestro unificado, UX-156; maqueta 13), the part that needs no new contract: the head (his
 * initials, never a photo until the rights are settled; age, nationality, position, club), the season by competition, the
 * last matches, the clubs he played for and the caps. Never shown here: injuries or any medical detail (only the profile
 * contract's state, source and date will be), the estimated line-up, the players' engine or player markets - all private.
 *
 * Shown only while FBI_PROFILES is on (`/auth/me`).
 */
import { useQuery } from "@tanstack/react-query";
import { PlayerStatsHub } from "./stats/PlayerStatsHub";
import { Link } from "@tanstack/react-router";
import { ChevronRight } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import { LiveApiError } from "@/lib/api/v1/client";
import type { PlayerDetail } from "@/lib/api/v1/types_center";
import { useAuth, useStatsSwitches } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatDate, formatKickoff } from "@/lib/time";
import { EntityHeader } from "@/product/shared/intelligence/Pieces";
import { Card, EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";
import { ageOf } from "./model";

function Block({
  title,
  children,
  testId,
}: {
  title: string;
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <Card className="space-y-3 p-4 sm:p-5" data-testid={testId}>
      <h2 className="text-subheading">{title}</h2>
      {children}
    </Card>
  );
}

const TH = "py-1 text-right font-medium";
const TD = "py-1.5 text-right";

function Seasons({ d }: { d: PlayerDetail }) {
  const rows = d.seasons.data ?? [];
  if (rows.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        {d.seasons.reason ?? t("profiles.player.none")}
      </p>
    );
  return (
    <div className="-mx-1 overflow-x-auto px-1">
      <table className="w-full min-w-[20rem] text-sm" data-testid="player-seasons">
        <thead>
          <tr className="text-left text-label text-subtle-foreground">
            <th scope="col" className="py-1 font-medium">
              {t("profiles.competition")}
            </th>
            <th scope="col" className={TH}>
              {t("profiles.player.apps")}
            </th>
            <th scope="col" className={TH}>
              {t("profiles.player.minutes")}
            </th>
            <th scope="col" className={TH}>
              {t("profiles.player.goals")}
            </th>
            <th scope="col" className={TH}>
              {t("profiles.player.assists")}
            </th>
          </tr>
        </thead>
        <tbody className="numeric">
          {rows.slice(0, 12).map((s, i) => (
            <tr key={`${s.competition}-${s.season}-${i}`} className="border-t border-border">
              <th scope="row" className="py-1.5 pr-2 text-left font-semibold">
                {s.competition}
                <span className="block text-caption font-normal text-muted-foreground">
                  {[s.season, s.team].filter(Boolean).join(" · ")}
                </span>
              </th>
              <td className={TD}>{s.apps}</td>
              <td className={TD}>{s.minutes ?? "—"}</td>
              <td className={TD}>{s.goals ?? "—"}</td>
              <td className={TD}>{s.assists ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Matches({ d }: { d: PlayerDetail }) {
  const rows = (d.matches.data ?? []).slice(0, 10);
  if (rows.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        {d.matches.reason ?? t("profiles.player.none")}
      </p>
    );
  return (
    <ul className="divide-y divide-border" data-testid="player-matches">
      {rows.map((m) => (
        <li key={m.fixture_id}>
          <Link
            to="/matches/$fixtureId"
            params={{ fixtureId: String(m.fixture_id) }}
            className="flex min-h-12 items-center gap-3 py-2 hover:text-primary"
          >
            <span className="numeric w-24 shrink-0 text-caption text-muted-foreground">
              {formatKickoff(m.kickoff_at)}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">
                {t("profiles.player.against", { team: m.opponent ?? "—" })}
              </span>
              <span className="block truncate text-caption text-muted-foreground">
                {m.competition}
              </span>
            </span>
            <span className="numeric shrink-0 text-caption text-muted-foreground">
              {m.minutes !== null ? t("profiles.player.min", { n: m.minutes }) : "—"}
              {m.goals ? ` · ${t("profiles.player.goalsN", { count: m.goals })}` : ""}
            </span>
            <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Career({ d }: { d: PlayerDetail }) {
  const spells = d.club_history?.data ?? [];
  if (spells.length === 0)
    return <p className="text-sm text-muted-foreground">{t("profiles.player.careerNone")}</p>;
  return (
    <ol className="space-y-2" data-testid="player-career">
      {spells.map((s, i) => (
        <li
          key={`${s.provider_team_id}-${i}`}
          className="flex items-baseline justify-between gap-3 text-sm"
        >
          {s.team_id ? (
            <Link
              to="/teams/$teamId"
              params={{ teamId: String(s.team_id) }}
              className="font-semibold hover:text-primary"
            >
              {s.team ?? "—"}
            </Link>
          ) : (
            <span className="font-semibold">{s.team ?? "—"}</span>
          )}
          <span className="numeric shrink-0 text-caption text-muted-foreground">
            {s.valid_from ? formatDate(s.valid_from) : "…"} –{" "}
            {s.valid_to ? formatDate(s.valid_to) : t("profiles.player.now")}
          </span>
        </li>
      ))}
    </ol>
  );
}

export function PlayerPage({ playerId }: { playerId: string }) {
  const open = useAuth().user?.profiles === true;
  const { stats: statsV2 } = useStatsSwitches();
  const q = useQuery({ ...live.player(playerId), enabled: open });
  if (!open)
    return (
      <Card className="p-4">
        <EmptyState title={t("profiles.closed")} />
      </Card>
    );
  if (q.isPending) return <SkeletonCards count={3} />;
  if (q.isError)
    return (
      <Card className={missing(q.error) ? "p-4" : undefined}>
        {missing(q.error) ? (
          <EmptyState title={t("profiles.player.missing")} />
        ) : (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        )}
      </Card>
    );
  const d = q.data.data;
  if (!d)
    return (
      <Card className="p-4">
        <EmptyState title={t("profiles.player.missing")} />
      </Card>
    );
  const p = d.player;
  const age = ageOf(p.birth_date);
  const caps = (d.national_caps?.data ?? []).filter((c) => c.appeared === true);
  const facts = [
    p.position
      ? t(
          `profiles.positions.${["Goalkeeper", "Defender", "Midfielder", "Attacker"].includes(p.position) ? p.position : "Other"}`,
        )
      : null,
    age !== null ? t("profiles.player.age", { n: age }) : null,
    p.nationality,
  ].filter((x): x is string => Boolean(x));
  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-5" data-testid="player-page">
      <EntityHeader kind="player" name={p.name} subtitle={p.team ?? null} facts={facts} />
      {statsV2 ? <PlayerStatsHub playerId={playerId} /> : null}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)] lg:items-start">
        <div className="flex min-w-0 flex-col gap-4">
          <Block title={t("profiles.player.season")}>
            <Seasons d={d} />
          </Block>
          <Block title={t("profiles.player.last")}>
            <Matches d={d} />
          </Block>
        </div>
        <div className="flex min-w-0 flex-col gap-4">
          {p.team_id ? (
            <Card className="p-4">
              <Link
                to="/teams/$teamId"
                params={{ teamId: String(p.team_id) }}
                className="flex items-center justify-between gap-2 text-sm font-semibold hover:text-primary"
              >
                {t("profiles.player.club", { team: p.team ?? "—" })}
                <ChevronRight aria-hidden className="h-4 w-4" />
              </Link>
            </Card>
          ) : null}
          <Block title={t("profiles.player.career")}>
            <Career d={d} />
          </Block>
          <Block title={t("profiles.player.caps")} testId="player-caps">
            <p className="text-sm">
              {caps.length > 0
                ? t("profiles.player.capsN", {
                    count: caps.length,
                    team: p.national_team ?? p.nationality ?? "",
                  })
                : t("profiles.player.capsNone")}
            </p>
          </Block>
          <Card className="p-4 text-caption text-muted-foreground">
            {t("profiles.player.coming")}
          </Card>
        </div>
      </div>
    </div>
  );
}

/** A profile that does not exist answers 404: said as such, not as an error to retry. */
function missing(error: unknown): boolean {
  return error instanceof LiveApiError && error.status === 404;
}
