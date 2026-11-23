/**
 * A point on the distribution of its position (plan EA, catalogue n.º 6; V2·2, V2·4): the shade is p10-p90 of the position's players
 * in the league (p25-p75 darker), the tick its median, the dot(s) the player(s); under it, where each one sits in words (AP-T03). Shows whether a difference is large or noise.
 */
import { isMissing } from "@/lib/api/v1/types_intelligence";
import type { StatFigure } from "@/lib/api/v1/types_stats";
import { figName, figValue } from "./format";
import { figurePlace } from "./howToRead";

export interface DistPlayer {
  name: string;
  figure: StatFigure;
  color: string;
}

export function DistributionRow({ players, testId }: { players: DistPlayer[]; testId?: string }) {
  const first = players[0]?.figure;
  if (!first) return null;
  const dist = [...players.map((p) => p.figure.distribution)].find((d) => !isMissing(d));
  const values = players.map((p) => (isMissing(p.figure.value) ? null : p.figure.value));
  const lo =
    isMissing(dist) || !dist
      ? Math.min(...values.filter((v): v is number => v !== null), 0)
      : dist.p10;
  const hi =
    isMissing(dist) || !dist
      ? Math.max(...values.filter((v): v is number => v !== null), 1)
      : Math.max(dist.p90, ...values.filter((v): v is number => v !== null));
  const span = Math.max(
    1e-6,
    (hi - Math.min(lo, ...values.filter((v): v is number => v !== null))) * 1.1,
  );
  const base = Math.min(lo, ...values.filter((v): v is number => v !== null));
  const at = (v: number) => `${Math.min(100, Math.max(0, ((v - base) / span) * 100))}%`;
  return (
    <div className="space-y-1" data-testid={testId}>
      <div className="flex items-baseline justify-between gap-2 text-small">
        <span className="text-foreground-soft">{figName(first.key)}</span>
        <span className="numeric">{players.map((p) => figValue(p.figure)).join(" · ")}</span>
      </div>
      <div className="relative h-4 rounded-full bg-elevated" aria-hidden>
        {dist && !isMissing(dist) ? (
          <>
            <span
              className="absolute inset-y-0 rounded-full bg-primary-soft"
              style={{ left: at(dist.p10), width: `calc(${at(dist.p90)} - ${at(dist.p10)})` }}
            />
            <span
              className="absolute inset-y-0.5 rounded-full bg-primary-dim/40"
              style={{ left: at(dist.p25), width: `calc(${at(dist.p75)} - ${at(dist.p25)})` }}
            />
            <span
              className="absolute -top-0.5 h-5 w-0.5 bg-foreground-soft/70"
              style={{ left: at(dist.p50) }}
            />
          </>
        ) : null}
        {players.map((p, i) =>
          values[i] === null ? null : (
            <span
              key={p.name}
              className="absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-card"
              style={{ left: at(values[i] as number), background: p.color }}
            />
          ),
        )}
      </div>
      <p className="text-small text-subtle-foreground">
        {players
          .map((p) => {
            const place = figurePlace(p.figure);
            return place === null ? null : players.length > 1 ? `${p.name}: ${place}` : place;
          })
          .filter((x) => x !== null)
          .join(" · ")}
      </p>
    </div>
  );
}
