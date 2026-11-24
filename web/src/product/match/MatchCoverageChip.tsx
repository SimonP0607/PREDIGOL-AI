/**
 * The chip «Cobertura X» of the Match Center's head (plan PM, lámina I04; UX-243): the level C-16 gives the competition the match is
 * in, written as the competition's own page writes it (B* / C* without odds), so a reader knows from the first screen how much of the
 * match PrediGol has. It only says what C-16 says: nothing here decides a level, and it draws nothing while the matrix is off
 * (`FBI_AVAILABILITY`), while the match's coverage is off (`FBI_MATCH_COVERAGE`) or while C-16 has not answered.
 */
import { useQuery } from "@tanstack/react-query";
import type { CompetitionAvailability } from "@/lib/api/v1/types_availability";
import { useAvailabilityOn, useMatchVizSwitches } from "@/lib/auth/AuthProvider";
import { competitionApi } from "@/product/competitions/api";
import { CoverageChip } from "@/product/shared/CoverageLevel";

/** The chip of a competition's C-16 summary; nothing when C-16 has none. */
export function CoverageChipOf({ summary }: { summary: CompetitionAvailability | null }) {
  if (!summary) return null;
  return (
    <div
      className="relative flex flex-wrap items-center gap-2 px-4 pt-1.5 sm:px-5"
      data-testid="match-coverage-chip"
    >
      <CoverageChip level={summary.summary} label={summary.summary_label} />
    </div>
  );
}

/** Reads the competition's summary (one request, the competition page's own) and draws the chip; off, it asks nothing. */
export function MatchCoverageChip({ competitionId }: { competitionId: number }) {
  const availabilityOn = useAvailabilityOn();
  const { coverage } = useMatchVizSwitches();
  const on = availabilityOn && coverage;
  const q = useQuery({
    ...competitionApi.availability(String(competitionId)),
    enabled: on,
    retry: false,
  });
  if (!on) return null;
  return <CoverageChipOf summary={q.data?.data.competitions[0] ?? null} />;
}
