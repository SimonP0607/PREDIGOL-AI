/**
 * Whether Inicio asks for yesterday's set (plan Inicio, P4). Today's board says it: `previous_day_open` is true only while
 * a pick of the day before is still to finish or settle. Anything else - the field false, missing (an API from before
 * UX-077), or the board not loaded yet - asks for nothing: the request is the cost P4 removed. Pure: the board is the argument.
 */
import type { DailyBoard } from "@/lib/api/v1/types_records";

export function wantsYesterday(
  board: Pick<DailyBoard, "previous_day_open"> | null | undefined,
): boolean {
  return board?.previous_day_open === true;
}
