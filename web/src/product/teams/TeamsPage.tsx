/**
 * «Equipos» (plan maestro unificado, UX-157; decision D-03): the destination the unified bar names, made only of pieces
 * that exist - the teams the reader follows (favourites), a search of clubs and national teams (GET /teams?q), and the
 * competitions PrediGol follows by country, each opening onto its teams (AP-E01: country → league → teams → profile; no
 * click of this page leads to Partidos). No maqueta of its own: it is the door to the profiles (maquetas 11-13). Shown only
 * while FBI_PROFILES is on.
 */
import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronRight, Search, Star } from "lucide-react";
import { fieldVariants } from "@/components/ui/field";
import { TeamLogo, TeamName } from "@/components/football/Logos";
import { live } from "@/lib/api/v1/queries";
import type { CompetitionSummary } from "@/lib/api/v1/types";
import { useAuth, usePmReaderSwitches } from "@/lib/auth/AuthProvider";
import { intlTag, t } from "@/lib/i18n";
import { useCountryAliases } from "@/lib/i18n/useCountryAliases";
import { cn } from "@/lib/utils";
import { formatKickoff } from "@/lib/time";
import { Card, EmptyState, PageTitle, SkeletonCards } from "@/product/shared/States";
import { REGIONS, regionOf, type Region } from "@/product/competitions/region";
import { LeagueRow } from "./CompetitionTeams";
import { countryName, isNation, teamLabel } from "./model";

export interface CountryGroup {
  country: string;
  label: string;
  /** ISO code of the country (from its competitions), for the region. */
  code: string | null;
  competitions: CompetitionSummary[];
}

/**
 * The countries by region (AP-E02: «todo el fútbol, por región y país»), in the order
 * the directory of competitions uses (Sudamérica first, where PrediGol starts). A region with no country is left out; a country the region list does not know goes
 * to «Otras» (never guessed).
 */
export function byRegion(
  groups: readonly CountryGroup[],
): { region: Region; countries: CountryGroup[] }[] {
  const by = new Map<Region, CountryGroup[]>();
  for (const g of groups) {
    const r = regionOf(g.country, g.code);
    by.set(r, [...(by.get(r) ?? []), g]);
  }
  return REGIONS.filter((r) => by.has(r)).map((region) => ({ region, countries: by.get(region)! }));
}

/** The national sides offered as a shortcut of the search (the provider's own English names; the page writes them in the reader's language). */
export const NATION_SHORTCUTS = [
  "Colombia",
  "Brazil",
  "Argentina",
  "Spain",
  "England",
  "Germany",
  "Netherlands",
  "South Africa",
] as const;

/** The competitions by country, the reader's own country (Colombia) first, then alphabetical. */
export function byCountry(list: readonly CompetitionSummary[]): CountryGroup[] {
  const by = new Map<string, CompetitionSummary[]>();
  for (const c of list) {
    if (!c.is_tracked) continue;
    const k = c.country ?? "World";
    by.set(k, [...(by.get(k) ?? []), c]);
  }
  return [...by.entries()]
    .map(([country, competitions]) => ({
      country,
      label: countryName(country) ?? country,
      competitions,
    }))
    .sort((a, b) =>
      a.country === "Colombia"
        ? -1
        : b.country === "Colombia"
          ? 1
          : a.label.localeCompare(b.label, intlTag()),
    )
    .map(({ country, label, competitions }) => ({
      country,
      label,
      code: competitions.find((c) => c.country_code)?.country_code ?? null,
      competitions: competitions.sort(
        (a, b) => (a.tier ?? 9) - (b.tier ?? 9) || a.name.localeCompare(b.name),
      ),
    }));
}

function useDebounced(value: string, ms = 300): string {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return v;
}

const ROW = "flex min-h-12 items-center gap-3 px-4 py-2.5 hover:bg-elevated";

export function TeamsPage() {
  const auth = useAuth();
  const open = auth.user?.profiles === true;
  const reader = auth.user?.role === "USER";
  // plan PM, PM-09-04: with the competition's page on, a competition leads to it; off, to its matches as before
  const { competitionPage } = usePmReaderSwitches();
  const [q, setQ] = useState("");
  const term = useDebounced(q.trim());
  const favorites = useQuery({ ...live.favorites, enabled: open && reader });
  const found = useQuery({ ...live.teamSearch(term), enabled: open && term.length >= 2 });
  // AP-B02: «España» also asks for «Spain»; one list, the national team first
  const { aliases, merge } = useCountryAliases(term, open && term.length >= 2);
  const aliased = useQueries({
    queries: aliases.map((a) => ({ ...live.teamSearch(a), enabled: open })),
  });
  const teamsFound = merge(
    found.data?.data ?? [],
    aliased.map((a) => a.data?.data ?? []),
    aliases,
  );
  const comps = useQuery({ ...live.competitions, enabled: open });
  const groups = useMemo(() => byCountry(comps.data?.data ?? []), [comps.data]);
  const regions = useMemo(() => byRegion(groups), [groups]);
  // «Tus equipos» say when each plays next: Inicio's own answer (GET /today), nothing new is asked.
  const today = useQuery({ ...live.today, enabled: open && reader });
  const nextOf = (teamId: number) =>
    today.data?.data?.following?.next?.find((n) => n.home.id === teamId || n.away.id === teamId) ??
    null;
  if (!open)
    return (
      <Card className="p-4">
        <EmptyState title={t("profiles.closed")} />
      </Card>
    );
  const mine = favorites.data && !favorites.data.suggested ? favorites.data.teams : [];
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="teams-page">
      <PageTitle title={t("profiles.teams.title")} subtitle={t("profiles.teams.subtitle")} />
      <label className="relative block">
        <span className="sr-only">{t("profiles.teams.search")}</span>
        <Search
          aria-hidden
          className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-subtle-foreground"
        />
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={t("profiles.teams.search")}
          data-testid="teams-search"
          className={cn(fieldVariants(), "pl-11")}
        />
      </label>
      {term.length >= 2 ? (
        <section aria-label={t("profiles.teams.results")}>
          {found.isPending ? (
            <SkeletonCards count={1} />
          ) : teamsFound.length === 0 ? (
            <p className="text-sm text-muted-foreground" data-testid="teams-none">
              {t("profiles.teams.none", { q: term })}
            </p>
          ) : (
            <ul
              className="card-surface divide-y divide-border rounded-card"
              data-testid="teams-results"
            >
              {teamsFound.slice(0, 20).map((team) => (
                <li key={team.id}>
                  <Link
                    to={isNation(team) ? "/nations/$teamId" : "/teams/$teamId"}
                    params={{ teamId: String(team.id) }}
                    className={ROW}
                  >
                    <TeamName
                      name={teamLabel(team)}
                      logo={team.logo_url}
                      size={22}
                      className="min-w-0 flex-1 font-semibold"
                    />
                    <span className="shrink-0 text-caption text-muted-foreground">
                      {countryName(team.country)}
                    </span>
                    <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
      <section aria-labelledby="teams-mine" className="space-y-2">
        <h2 id="teams-mine" className="flex items-center gap-2 text-title">
          <Star aria-hidden className="h-4 w-4 text-gold" />
          {t("profiles.teams.mine")}
        </h2>
        {mine.length === 0 ? (
          <Card className="p-4">
            <p className="text-sm text-muted-foreground">{t("profiles.teams.mineNone")}</p>
            <Link
              to="/profile/$section"
              params={{ section: "football" }}
              className="mt-2 inline-block text-sm font-semibold text-primary hover:underline"
            >
              {t("profiles.teams.choose")}
            </Link>
          </Card>
        ) : (
          <ul
            className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4"
            data-testid="teams-mine-list"
          >
            {mine.map((team) => {
              const next = nextOf(team.id);
              const rival = next ? (next.home.id === team.id ? next.away : next.home) : null;
              return (
                <li key={team.id} className="min-w-0">
                  <Link
                    to="/teams/$teamId"
                    params={{ teamId: String(team.id) }}
                    data-testid="teams-mine-card"
                    className="card-surface flex h-full min-h-[8.5rem] flex-col items-center gap-2 rounded-card p-3 text-center hover:bg-elevated"
                  >
                    <TeamLogo src={team.logo_url} name={team.name} size={44} />
                    <span className="line-clamp-2 max-w-full break-words text-sm font-semibold leading-tight">
                      {team.name}
                    </span>
                    <span className="text-caption text-muted-foreground" data-testid="teams-next">
                      {next && rival
                        ? t("profiles.teams.next", {
                            when: formatKickoff(next.kickoff_at),
                            rival: rival.name,
                          })
                        : t("profiles.teams.nextNone")}
                    </span>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </section>
      <section aria-labelledby="teams-nations" className="space-y-2" data-testid="teams-nations">
        <h2 id="teams-nations" className="text-title">
          {t("profiles.teams.nations")}
        </h2>
        <ul className="flex flex-wrap gap-2">
          {NATION_SHORTCUTS.map((en) => {
            const label = countryName(en) ?? en;
            return (
              <li key={en}>
                <button
                  type="button"
                  onClick={() => setQ(label)}
                  data-testid="teams-nation"
                  className="tap-y relative inline-flex min-h-11 items-center rounded-full border border-border bg-elevated px-3.5 text-sm font-semibold text-foreground-soft hover:text-foreground"
                >
                  {label}
                </button>
              </li>
            );
          })}
        </ul>
        <p className="text-caption text-muted-foreground">{t("profiles.teams.nationsHelp")}</p>
      </section>
      <section aria-labelledby="teams-comps" className="space-y-2">
        <h2 id="teams-comps" className="text-title">
          {t("profiles.teams.competitions")}
        </h2>
        {comps.isPending ? (
          <SkeletonCards count={2} />
        ) : (
          <div className="space-y-2" data-testid="teams-competitions">
            {regions.map(({ region, countries }, ri) => (
              <details
                key={region}
                open={ri === 0}
                className="group/r card-surface rounded-card"
                data-testid="teams-region"
                data-region={region}
              >
                <summary className="flex min-h-12 cursor-pointer list-none items-center gap-3 px-4 py-2.5 [&::-webkit-details-marker]:hidden">
                  <span className="min-w-0 flex-1 text-sm font-semibold">
                    {t(`competitions.region.${region}`)}
                  </span>
                  <span className="numeric text-caption text-subtle-foreground">
                    {t("profiles.teams.countries", { n: countries.length })}
                  </span>
                  <ChevronRight
                    aria-hidden
                    className="h-4 w-4 shrink-0 text-subtle-foreground transition-transform group-open/r:rotate-90"
                  />
                </summary>
                <div className="divide-y divide-border border-t border-border">
                  {countries.map((g) => (
                    <details key={g.country} className="group/c">
                      <summary className="flex min-h-12 cursor-pointer list-none items-center gap-3 px-4 py-2.5 [&::-webkit-details-marker]:hidden">
                        <span className="min-w-0 flex-1 text-sm font-semibold">{g.label}</span>
                        <span className="numeric text-caption text-subtle-foreground">
                          {g.competitions.length}
                        </span>
                        <ChevronRight
                          aria-hidden
                          className="h-4 w-4 shrink-0 text-subtle-foreground transition-transform group-open/c:rotate-90"
                        />
                      </summary>
                      <ul className="pb-2">
                        {g.competitions.map((c) => (
                          <LeagueRow key={c.id} competition={c} competitionPage={competitionPage} />
                        ))}
                      </ul>
                    </details>
                  ))}
                </div>
              </details>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
