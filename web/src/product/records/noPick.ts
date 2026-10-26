/**
 * A day without picks, told honestly (plan UX, A9; section 24): «Hoy ningún partido cumplió las condiciones para publicar
 * un pick. Preferimos no publicar a publicar por publicar», and under it the reason - the furthest stage the day's
 * selections reached in the published set's own funnel and its commonest reason (GET /today's no_pick, qualified only).
 * While the day's set does not exist yet: «Todavía estamos revisando los partidos de hoy», with no hour promised.
 *
 * Never filled with evaluation picks, never «valor»: a reason this page has no sentence for is left out, not shown raw.
 */
import type { UseQueryResult } from "@tanstack/react-query";
import { hasKey, t } from "@/lib/i18n";
import type { Envelope } from "@/lib/api/v1/types";
import type { NoPick } from "@/lib/api/v1/types_today";

export type NoPickLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry: () => void }
  | { status: "ok"; value: NoPick | null };

/** The reason as a query answered it: GET /today (its no_pick section) or GET /today/no-pick. */
export function noPickLoad<T>(
  query: UseQueryResult<Envelope<T>>,
  pick: (data: T) => NoPick | null,
): NoPickLoad {
  if (query.isPending) return { status: "pending" };
  if (query.isError)
    return { status: "error", error: query.error, retry: () => void query.refetch() };
  const data = query.data.data;
  return { status: "ok", value: data === null || data === undefined ? null : pick(data) };
}

export type NoPickView =
  /** The day has picks after all (the set was chosen since the board was read): the list's own empty state. */
  | { kind: "generic" }
  | { kind: "reviewing" }
  | { kind: "no_matches" }
  | { kind: "none"; why: string | null };

/** The reason in the reader's words: the code's own sentence, else its stage's, else none. */
export function reasonText(n: Pick<NoPick, "stage" | "reason">): string | null {
  if (n.reason && hasKey(`records.noPick.reason.${n.reason}`)) {
    return t(`records.noPick.reason.${n.reason}`);
  }
  if (n.stage && hasKey(`records.noPick.stage.${n.stage}`))
    return t(`records.noPick.stage.${n.stage}`);
  return null;
}

export function noPickView(n: NoPick | null): NoPickView {
  if (n === null || n.state === "picks") return { kind: "generic" };
  if (n.state === "reviewing") return { kind: "reviewing" };
  if (n.reason === "no_matches") return { kind: "no_matches" };
  return { kind: "none", why: reasonText(n) };
}
