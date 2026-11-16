/**
 * The reader's parlays as the history of sheet L05 (plan maestro unificado, UX-148): the last 30 days in three figures with
 * their sample, «Todos / Pendientes / Liquidados», the parlays under the day they were saved, and under each one how its
 * legs stand - so far on a pending parlay, «acertó 3 de 4» on a lost one. Everything is read from what the API answered:
 * the counts from GET /me/history (30 days, the sample rule of Mis picks), the legs' states from GET /me/parlays.
 */
import type { ReactNode } from "react";
import { t } from "@/lib/i18n";
import { DASH, fmtInt } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import type { HistoryGroup, UserParlay } from "@/lib/api/v1/types_records";
import { dayKey } from "@/lib/time";
import { Card } from "@/product/shared/States";
import { Units } from "./Badges";

export type ParlayFilter = "all" | "pending" | "settled";

const SETTLED = new Set(["WON", "LOST", "VOID", "PARTIAL_VOID"]);

export function isSettled(p: Pick<UserParlay, "status">): boolean {
  return SETTLED.has(p.status);
}

export function filterParlays(list: readonly UserParlay[], f: ParlayFilter): UserParlay[] {
  if (f === "all") return [...list];
  return list.filter((p) => (f === "settled" ? isSettled(p) : !isSettled(p)));
}

/** The parlays under the product day they were saved, newest first (the API's order is kept inside a day). */
export function parlaysByDay(
  list: readonly UserParlay[],
): { day: string; at: string; parlays: UserParlay[] }[] {
  const out: { day: string; at: string; parlays: UserParlay[] }[] = [];
  for (const p of list) {
    const day = dayKey(p.created_at);
    const last = out[out.length - 1];
    if (last && last.day === day) last.parlays.push(p);
    else out.push({ day, at: p.created_at, parlays: [p] });
  }
  return out;
}

/** How the legs stand: won (a half or a push counts as not lost), lost, still to play. */
export function legTally(p: Pick<UserParlay, "legs">): {
  won: number;
  lost: number;
  open: number;
  total: number;
} {
  let won = 0;
  let lost = 0;
  let open = 0;
  for (const l of p.legs) {
    if (l.status === "PENDING") open += 1;
    else if (l.status === "LOSS" || l.status === "HALF_LOSS") lost += 1;
    else won += 1;
  }
  return { won, lost, open, total: p.legs.length };
}

/** A pending parlay's progress: one segment per leg, in its state; and the words for it. */
export function LegProgress({ parlay }: { parlay: UserParlay }) {
  const tally = legTally(parlay);
  return (
    <span className="flex items-center gap-2" data-testid="my-parlay-progress">
      <span className="numeric text-caption text-muted-foreground">
        {t("records.mine.parlays.progress", { won: tally.won, total: tally.total })}
      </span>
      <span aria-hidden className="flex gap-1">
        {parlay.legs.map((l) => (
          <span
            key={l.leg_no}
            className={cn(
              "h-1.5 w-5 rounded-full",
              l.status === "PENDING"
                ? "bg-elevated"
                : l.status === "LOSS" || l.status === "HALF_LOSS"
                  ? "bg-negative"
                  : "bg-positive",
            )}
          />
        ))}
      </span>
    </span>
  );
}

/** Under a lost parlay: how many legs it got right, and why one is enough to lose it. */
export function LostNote({ parlay }: { parlay: UserParlay }) {
  if (parlay.status !== "LOST") return null;
  const tally = legTally(parlay);
  return (
    <p className="text-caption text-muted-foreground" data-testid="my-parlay-lost-note">
      {t("records.mine.parlays.lostNote", { won: tally.won, total: tally.total })}
    </p>
  );
}

function Figure({ value, label, tone }: { value: ReactNode; label: string; tone?: string }) {
  return (
    <div className="min-w-0">
      <dd className={cn("numeric font-display text-2xl font-bold leading-none", tone)}>{value}</dd>
      <dt className="mt-1 text-caption text-muted-foreground">{label}</dt>
    </div>
  );
}

/** «Últimos 30 días» of the reader's own parlays: settled, won of decided, the result - with the sample's sentence. */
export function ParlaysMonth({ group }: { group: HistoryGroup | undefined }) {
  if (!group || group.total === 0) return null;
  const settled = group.total - group.pending;
  const decided = group.won + group.lost;
  return (
    <Card className="p-4" data-testid="my-parlays-month">
      <p className="text-overline text-muted-foreground">{t("records.mine.parlays.month")}</p>
      <dl className="mt-3 grid grid-cols-3 gap-3">
        <Figure
          value={fmtInt(settled)}
          label={t("records.mine.parlays.settledWord", { count: settled })}
        />
        <Figure
          value={
            decided > 0 ? t("records.mine.parlays.wonOf", { won: group.won, total: decided }) : DASH
          }
          label={t("records.mine.parlays.wonWord")}
        />
        <Figure
          value={group.profit_units === null ? DASH : <Units value={group.profit_units} />}
          label={t("records.mine.parlays.result")}
        />
      </dl>
      {group.conclusive !== true && settled > 0 ? (
        <p className="mt-3 text-caption text-muted-foreground">
          {t("records.mine.parlays.noTrend", { count: settled })}
        </p>
      ) : null}
    </Card>
  );
}
