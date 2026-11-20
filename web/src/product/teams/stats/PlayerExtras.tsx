/**
 * The player's profile with the new data (plan PM, PM-08-06; UX-180; lámina I06), under the advanced statistics: «Bajo los palos»
 * and «Con el balón» for a goalkeeper, «Penaltis y fueras de juego» for everyone. Each figure carries its unit, its sample and its
 * origin («dato de API-Football» or PrediGol's own count); a missing one keeps its reason; with the competition's player data at
 * level C the block says it is partial, at D or with a short sample it is not drawn and one line says why (PM-14-01's states).
 * A goalkeeper's goals prevented stay out until the provider's field passes its probe, and the page says so. No chart: figures.
 *
 * Shown only while `FBI_PLAYER_PROFILE_EXTRAS` is on.
 */
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Hand, ShieldAlert, Target } from "lucide-react";
import type { CoverageLevel } from "@/lib/api/v1/types_availability";
import type { PlayerBody, StatsEntity } from "@/lib/api/v1/types_stats";
import { useAuth } from "@/lib/auth/AuthProvider";
import { localFixed, localInt } from "@/lib/i18n/format";
import { familyLevel } from "@/product/competitions/model";
import { competitionApi } from "@/product/competitions/api";
import { NotOffered, PartialCoverage, ThinSample, UnderReview } from "@/product/shared/Unavailable";
import { Card } from "@/product/shared/States";
import { hasValues, playerExtrasView, type ShownFigure } from "./extrasModel";
import { t } from "./playerText";

function figureValue(f: ShownFigure): string {
  if (f.value === null) return "—";
  if (f.unit === "porcentaje") return `${localFixed(f.value, 1)} %`;
  if (f.unit === "total") return localInt(Math.round(f.value));
  return localFixed(f.value, 2);
}

function Tile({ f }: { f: ShownFigure }) {
  return (
    <li
      className="rounded-field border border-border bg-elevated/40 p-3"
      data-testid={`extra-${f.key}`}
      data-origin={f.origin}
    >
      <p className="numeric font-display text-2xl font-bold leading-tight">{figureValue(f)}</p>
      <p className="text-small text-foreground-soft">{t(`players.fig.${f.key}`)}</p>
      <p className="text-caption text-muted-foreground">
        {f.value === null
          ? t(`players.missing.${f.missing ?? "sin_datos"}`)
          : [
              t(`players.unit.${f.unit}`),
              f.league !== null
                ? t("players.league", {
                    v:
                      f.unit === "porcentaje"
                        ? `${localFixed(f.league, 1)} %`
                        : localFixed(f.league, 2),
                  })
                : null,
              t("players.matches", { n: f.matches }),
            ]
              .filter(Boolean)
              .join(" · ")}
      </p>
    </li>
  );
}

function Block({
  title,
  icon,
  figures,
  source,
  children,
  testId,
}: {
  title: string;
  icon: ReactNode;
  figures: ShownFigure[];
  source: string;
  children?: ReactNode;
  testId: string;
}) {
  if (figures.length === 0) return null;
  return (
    <Card className="space-y-3 p-4 sm:p-5" data-testid={testId}>
      <h2 className="flex items-center gap-2 text-subheading">
        <span aria-hidden className="text-subtle-foreground">
          {icon}
        </span>
        {title}
      </h2>
      {hasValues(figures) ? (
        <ul className="grid grid-cols-2 gap-2">
          {figures.map((f) => (
            <Tile key={f.key} f={f} />
          ))}
        </ul>
      ) : (
        <p className="text-small text-muted-foreground" data-unavailable="muestra_insuficiente">
          {t("players.blockMissing", { matches: Math.max(0, ...figures.map((f) => f.matches)) })}
        </p>
      )}
      {children}
      <p className="text-caption text-subtle-foreground">{source}</p>
    </Card>
  );
}

export function PlayerExtrasView({
  body,
  level,
}: {
  body: PlayerBody;
  /** The level of the competition's player data in C-16; null when C-16 is not published. */
  level: CoverageLevel | null;
}) {
  const v = playerExtrasView(body, level);
  const sampleLine = t("players.sample", {
    n: v.sample.appearances,
    minutes: localInt(v.sample.minutes),
  });
  if (v.state === "no_ofrece")
    return (
      <NotOffered
        subjects={[t("players.blocks.discipline").toLowerCase()].concat(
          v.keeper ? [t("players.blocks.underPosts").toLowerCase()] : [],
        )}
      />
    );
  if (v.state === "muestra_corta")
    return (
      <ThinSample
        subject={t("players.thinSubject")}
        n={v.sample.appearances}
        icon={<Target aria-hidden className="h-5 w-5" />}
      />
    );
  const partial =
    v.state === "parcial" ? <PartialCoverage subjects={[t("players.partialSubject")]} /> : null;
  return (
    <section
      aria-label={t("players.title")}
      className="grid gap-4 lg:grid-cols-2"
      data-testid="player-extras"
      data-keeper={v.keeper}
    >
      {v.keeper ? (
        <Block
          title={t("players.blocks.underPosts")}
          icon={<Hand className="h-4 w-4" />}
          figures={v.underPosts}
          source={t("players.sourceMixed")}
          testId="extras-under-posts"
        >
          <p className="text-caption text-muted-foreground">{sampleLine}</p>
          {v.goalsPreventedHeld ? (
            <UnderReview
              subject={t("players.goalsPrevented")}
              why={t("players.goalsPreventedWhy")}
            />
          ) : null}
          {partial}
        </Block>
      ) : null}
      {v.keeper ? (
        <Block
          title={t("players.blocks.withBall")}
          icon={<Target className="h-4 w-4" />}
          figures={v.withBall}
          source={t("players.sourcePredigol")}
          testId="extras-with-ball"
        />
      ) : null}
      <Block
        title={t("players.blocks.discipline")}
        icon={<ShieldAlert className="h-4 w-4" />}
        figures={v.discipline}
        source={t("players.sourceProvider")}
        testId="extras-discipline"
      >
        {v.keeper ? null : <p className="text-caption text-muted-foreground">{sampleLine}</p>}
        {v.keeper ? null : partial}
      </Block>
    </section>
  );
}

/** The blocks of a player's statistics entity, with the level of its competition's player data when C-16 is published. */
export function PlayerExtras({ entity, body }: { entity: StatsEntity; body: PlayerBody }) {
  const availabilityOn = useAuth().user?.availability === true;
  const id = String(entity.competition.competition.id);
  const q = useQuery({
    ...competitionApi.availability(id),
    enabled: availabilityOn,
    retry: false,
  });
  const competition = q.data?.data.competitions[0] ?? null;
  return <PlayerExtrasView body={body} level={familyLevel(competition, "player_stats")} />;
}
