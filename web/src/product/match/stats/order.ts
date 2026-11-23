/**
 * The blocks of «Estadísticas» before kick-off, in the order a reader reads them (plan UX, AP-P05): how the two teams come in,
 * the season from the league table, and last the cross of the two in charts (FBI_STATS_V2). The tab's own title already says it is
 * before the match, so no line of waiting precedes them. A block without data is not drawn by its own component, as before.
 */
export type PreMatchBlock = "profile" | "season" | "cross";

export function preMatchBlocks(statsV2: boolean): PreMatchBlock[] {
  return statsV2 ? ["profile", "season", "cross"] : ["profile", "season"];
}
