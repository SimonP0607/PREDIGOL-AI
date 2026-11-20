/**
 * The reads of the competition pages (plan PM, PM-09-04 and PM-09-05; UX-178, UX-179, BE-082), kept in the screens' own lazy chunk
 * rather than in `lib/api/v1/client.ts`: the first visit's JS sits at its ceiling and cannot grow (UX-139).
 */
import { getJson } from "@/lib/api/v1/client";
import type { Envelope } from "@/lib/api/v1/types";
import type { Availability } from "@/lib/api/v1/types_availability";
import type { SeasonTables } from "@/lib/api/v1/types_season_tables";

const MINUTE = 60_000;

export const competitionApi = {
  /** C-16: every tracked competition with its summary and families (the directory). 404 while FBI_AVAILABILITY is off. */
  directory: {
    queryKey: ["v1", "availability", "directory"],
    queryFn: () => getJson<Envelope<Availability>>("/availability/competitions"),
    staleTime: 10 * MINUTE,
  },
  /** C-16: one competition, its seasons and every cell. 404 while FBI_AVAILABILITY is off. */
  availability: (id: string) => ({
    queryKey: ["v1", "availability", "competition", id],
    queryFn: () => getJson<Envelope<Availability>>(`/availability/competitions/${id}`),
    staleTime: 10 * MINUTE,
  }),
  /** BE-082: the season tables computed from the regulation. 404 while FBI_COMPETITION_TABLES is off; kept 5 min by the API. */
  seasonTables: (id: string, season?: number) => ({
    queryKey: ["v1", "season-tables", id, season ?? "newest"],
    queryFn: () =>
      getJson<Envelope<SeasonTables | null>>(`/competitions/${id}/season-tables`, { season }),
    staleTime: 5 * MINUTE,
  }),
};
