/**
 * The world directory of competitions (plan PM, PM-09-05; UX-179; lámina I08): every competition PrediGol follows with the summary
 * of its coverage (C-16's directory, the only screen that reads the summary) and its editorial priority (C-16 1.2.0), grouped by
 * region and country, filtered by name or country, level, «solo destacadas» and «las que sigo». The level measures the data that
 * arrived this season, not the quality of the league; the priority says where PrediGol puts more attention.
 */
import type { CompetitionSummary } from "@/lib/api/v1/types";
import type { CompetitionAvailability, CoverageLevel } from "@/lib/api/v1/types_availability";
import { isMissing } from "@/lib/api/v1/types_intelligence";
import { REGIONS, regionOf, type Region } from "./region";

export type Priority = "P0" | "P1" | "P2" | "P3" | "P4";
export const LEVELS: readonly CoverageLevel[] = ["A", "B", "C", "D", "MI"];

export interface DirectoryEntry {
  id: number;
  name: string;
  /** The provider's English country name (the page translates it); null for an international competition. */
  country: string | null;
  countryCode: string | null;
  region: Region;
  type: string;
  level: CoverageLevel;
  label: string;
  priority: Priority | null;
  featured: boolean;
}

export interface DirectoryFilter {
  query: string;
  level: CoverageLevel | "all";
  featured: boolean;
  mine: boolean;
}

export const NO_FILTER: DirectoryFilter = { query: "", level: "all", featured: false, mine: false };

function plain(s: string): string {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
}

/** C-16's directory joined to the catalogue (`/competitions`) by id: the country's code and the type come from the catalogue. */
export function directoryEntries(
  availability: readonly CompetitionAvailability[],
  catalogue: readonly CompetitionSummary[],
): DirectoryEntry[] {
  const byId = new Map(catalogue.map((c) => [c.id, c]));
  return availability.map((a) => {
    const c = byId.get(a.competition_id);
    const country = isMissing(a.country) ? (c?.country ?? null) : a.country;
    const code = c?.country_code ?? null;
    const raw = a.priority;
    const priority = raw === undefined || isMissing(raw) ? null : raw;
    return {
      id: a.competition_id,
      name: a.name,
      country,
      countryCode: code,
      region: regionOf(country, code),
      type: c?.type ?? "league",
      level: a.summary,
      label: a.summary_label,
      priority,
      featured: priority === "P0" || priority === "P1",
    };
  });
}

/** `countryName` is the country as the page writes it (translated), so a search in Spanish finds «España». */
export function filterEntries(
  entries: readonly DirectoryEntry[],
  f: DirectoryFilter,
  mine: ReadonlySet<number>,
  countryName: (e: DirectoryEntry) => string = (e) => e.country ?? "",
): DirectoryEntry[] {
  const q = plain(f.query);
  return entries.filter(
    (e) =>
      (f.level === "all" || e.level === f.level) &&
      (!f.featured || e.featured) &&
      (!f.mine || mine.has(e.id)) &&
      (!q ||
        plain(e.name).includes(q) ||
        plain(countryName(e)).includes(q) ||
        plain(e.country ?? "").includes(q)),
  );
}

/** How many competitions each level chip counts (before the level filter, after the others). */
export function levelCounts(
  entries: readonly DirectoryEntry[],
): Record<CoverageLevel | "all", number> {
  const out = { all: entries.length, A: 0, B: 0, C: 0, D: 0, MI: 0 };
  for (const e of entries) out[e.level] += 1;
  return out;
}

const LEVEL_ORDER: Record<CoverageLevel, number> = { A: 0, B: 1, C: 2, D: 3, MI: 4 };
const PRIORITY_ORDER: Record<Priority, number> = { P0: 0, P1: 1, P2: 2, P3: 3, P4: 4 };

export interface RegionGroup {
  region: Region;
  entries: DirectoryEntry[];
  /** How many have coverage A: what the folded regions say. */
  withA: number;
}

/** By region in the lámina's order; inside, the featured first, then the deeper level, then the name. */
export function byRegion(entries: readonly DirectoryEntry[]): RegionGroup[] {
  const groups = new Map<Region, DirectoryEntry[]>();
  for (const e of entries) groups.set(e.region, [...(groups.get(e.region) ?? []), e]);
  return REGIONS.filter((r) => groups.has(r)).map((region) => {
    const list = [...(groups.get(region) ?? [])].sort(
      (a, b) =>
        Number(b.featured) - Number(a.featured) ||
        (a.priority ? PRIORITY_ORDER[a.priority] : 9) -
          (b.priority ? PRIORITY_ORDER[b.priority] : 9) ||
        LEVEL_ORDER[a.level] - LEVEL_ORDER[b.level] ||
        a.name.localeCompare(b.name),
    );
    return { region, entries: list, withA: list.filter((e) => e.level === "A").length };
  });
}

/** How many distinct countries the list covers (international competitions apart). */
export function countryCount(entries: readonly DirectoryEntry[]): number {
  return new Set(
    entries.filter((e) => e.country && e.region !== "internacional").map((e) => e.country),
  ).size;
}
