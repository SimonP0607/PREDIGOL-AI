/**
 * What C-16 says of a match's blocks, for the Match Center's new pieces (plan PM, block 10: PM-10-01 «aparece solo con estadísticas
 * de equipo de nivel B o superior»). C-16 answers only while `FBI_AVAILABILITY` is on: off, or while it has not answered, a piece
 * falls back to the match's own data (it is drawn only when every figure it needs is there). Nothing here decides a level - it reads
 * what `fbi.coverage.resolve` already decided.
 */
import { useQuery } from "@tanstack/react-query";
import { useAvailabilityOn } from "@/lib/auth/AuthProvider";
import { live } from "@/lib/api/v1/queries";
import type {
  BlockAvailability,
  CoverageLevel,
  MatchAvailability,
} from "@/lib/api/v1/types_availability";
import { present } from "@/lib/api/v1/types_intelligence";

/** The C-16 keys of a match's blocks (`fbi.coverage.resolve.BLOCKS`). */
export type MatchBlockKey =
  | "events"
  | "lineups"
  | "team_stats"
  | "shots_on_target"
  | "fouls"
  | "xg"
  | "player_stats"
  | "referee";

/**
 * Whether C-16 lets a block be drawn: true at A or B with the datum delivered, false otherwise, null when C-16 said nothing of it
 * (off, not answered, or the block not measured) - the caller then decides from the match's own data.
 */
export function blockAllows(
  blocks: readonly BlockAvailability[] | null | undefined,
  key: MatchBlockKey,
): boolean | null {
  const block = blocks?.find((b) => b.key === key);
  if (!block) return null;
  const level = present(block.level);
  if (level === null || block.reason === "sin_medir") return null;
  return block.exists && (level === "A" || level === "B");
}

/** What C-16 says of a match (its blocks and markets), or null while it is off or has not answered. */
export function useMatchAvailability(fixtureId: string): MatchAvailability | null {
  const on = useAvailabilityOn();
  const q = useQuery({ ...live.matchAvailability(fixtureId), enabled: on, retry: false });
  if (!on) return null;
  return present(q.data?.data?.match) ?? null;
}

/** The blocks C-16 gives for a match, or null while it is off or has not answered. */
export function useMatchBlocks(fixtureId: string): BlockAvailability[] | null {
  return useMatchAvailability(fixtureId)?.blocks ?? null;
}

/**
 * The level C-16 gives a block, when it measured it (null: not said, not measured). A level D block is one the competition does not
 * deliver at all - the tab or block that rests on it has nothing to show there.
 */
export function blockLevel(
  blocks: readonly BlockAvailability[] | null | undefined,
  key: MatchBlockKey,
): CoverageLevel | null {
  const block = blocks?.find((b) => b.key === key);
  if (!block || block.reason === "sin_medir") return null;
  return present(block.level);
}
