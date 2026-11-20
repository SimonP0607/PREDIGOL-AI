/**
 * A league table as the Match Center draws it (plan F2): every number named by its short label, with the long one on a tap, on
 * hover and for assistive technology, and the rows of the teams that matter highlighted. Shared by the Match Center
 * (`ContextBlocks.tsx`) and a competition's page (plan PM, PM-09-04; UX-178).
 */
import { TeamName } from "@/components/football/Logos";
import { Hint } from "@/components/system/Hint";
import type { TableRow } from "@/lib/api/v1/types_center";
import { t } from "@/lib/i18n";
import { fmtLine } from "@/lib/i18n/format";
import { cn } from "@/lib/utils";
import { rankedRows } from "./standings";

/** Widths of the figure columns. The tables are `table-fixed`: the header row is the first row, so it is what sets them. */
const COLUMN_WIDTHS = {
  regular: { rank: "w-8", played: "w-9", diff: "w-11", points: "w-10" },
  compact: { rank: "w-7", played: "w-8", diff: "w-10", points: "w-9" },
} as const;

/**
 * The header both tables of this block share (plan F2): a number in a table is never bare. Each column is named by its short
 * label, with the long one on a tap, on hover and for assistive technology (`Hint`).
 */
export function StandingsHead({ size }: { size: keyof typeof COLUMN_WIDTHS }) {
  const w = COLUMN_WIDTHS[size];
  return (
    <thead>
      <tr className="text-caption text-subtle-foreground">
        <th scope="col" className={cn(w.rank, "pb-1.5 text-left font-medium")}>
          <Hint text={t("match.standings.rankLong")}>{t("match.standings.rank")}</Hint>
        </th>
        <th scope="col" className="pb-1.5 text-left font-medium">
          {t("match.standings.team")}
        </th>
        <th scope="col" className={cn(w.played, "pb-1.5 text-right font-medium")}>
          <Hint text={t("match.standings.playedLong")}>{t("match.standings.played")}</Hint>
        </th>
        <th scope="col" className={cn(w.diff, "pb-1.5 text-right font-medium")}>
          <Hint text={t("match.standings.goalDiffLong")}>{t("match.standings.goalDiff")}</Hint>
        </th>
        <th scope="col" className={cn(w.points, "pb-1.5 text-right font-medium")}>
          <Hint text={t("match.standings.pointsLong")}>{t("match.standings.points")}</Hint>
        </th>
      </tr>
    </thead>
  );
}

/** One table of the full view, named for assistive technology, with the two teams of the match highlighted. */
export function FullTable({
  rows,
  mine,
  label,
}: {
  rows: TableRow[];
  mine: ReadonlySet<number>;
  label: string;
}) {
  return (
    <table className="w-full table-fixed text-xs">
      <caption className="sr-only">{label}</caption>
      <StandingsHead size="compact" />
      <tbody className="divide-y divide-border/40">
        {rankedRows(rows, "all").map(({ rank, row, figures: f }) => (
          <tr
            key={row.team_id}
            className={cn(mine.has(row.team_id) && "bg-primary/8 font-semibold")}
          >
            <td className="numeric py-1 text-muted-foreground">{rank}</td>
            <td className="py-1 pr-2">
              <TeamName name={row.team} logo={row.team_logo} size={16} wrap />
            </td>
            <td className="numeric py-1 text-right text-muted-foreground">{f.played}</td>
            <td className="numeric py-1 text-right">{fmtLine(f.goalDiff, true)}</td>
            <td className="numeric py-1 text-right font-semibold">{f.points}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
