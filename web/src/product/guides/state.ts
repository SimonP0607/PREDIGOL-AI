/**
 * The guides' state as the page keeps it: the list GET /auth/me brings, and what a write changes in it at once (the API's
 * answer replaces it afterwards). The rules are the server's (fbi.customer.guides) - within a version the status never goes
 * down, a lower version changes nothing - so the page and the API agree before the answer arrives.
 */
import type { Me } from "@/lib/api/v1/types_auth";
import type { GuideIn, GuideKey, GuideState, GuideStatus } from "@/lib/api/v1/types_guides";

const RANK: Record<GuideStatus, number> = { pending: 0, in_progress: 1, skipped: 2, completed: 3 };

export function seenOf(me: Pick<Me, "guides"> | null | undefined, guide: GuideKey) {
  return me?.guides?.find((g) => g.guide === guide);
}

/** What the server would record for a write (the same rules), given what it holds now. */
export function applied(
  current: GuideState | undefined,
  guide: GuideKey,
  body: GuideIn,
  at: string,
): GuideState {
  if (current && body.version < current.version) return current;
  if (current && body.version === current.version) {
    if (RANK[body.status] < RANK[current.status]) return current;
    if (
      body.status === current.status &&
      (body.status === "completed" || body.status === "skipped")
    )
      return current;
  }
  const same = current !== undefined && current.version === body.version;
  const started = body.status === "pending" ? null : ((same ? current.started_at : null) ?? at);
  return {
    guide,
    version: body.version,
    status: body.status,
    step: body.step,
    first_seen_at: current?.first_seen_at ?? at,
    started_at: started,
    completed_at: body.status === "completed" ? at : null,
    skipped_at: body.status === "skipped" ? at : null,
  };
}

/** The account with one guide's state put in (or replaced). */
export function withGuide(me: Me, state: GuideState): Me {
  const rest = (me.guides ?? []).filter((g) => g.guide !== state.guide);
  return { ...me, guides: [...rest, state] };
}
