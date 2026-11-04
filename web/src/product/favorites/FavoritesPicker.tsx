/**
 * Choosing the leagues and teams a reader follows (plan UX, A13; section 20): the welcome's «Tu fútbol» and the profile's
 * own card. A phone first, for 133 followed leagues and thousands of teams (production, 26-oct-2026):
 *
 *   - the reader's choice on top, as chips that remove with a tap, with the counts against the limits;
 *   - one search for a league or a team (two letters or more, without accents or case - the API's own folding): the
 *     leagues are matched here by name or country, the teams by the API;
 *   - without a search, the leagues by country, each country folded under a 44 px row that says how many it has and how
 *     many are chosen (Colombia open first; the international ones last).
 *
 * Every target 44 px; the limits show before the reader reaches them and, at a limit, nothing more is added. A keyboard
 * reaches everything: the toggles are buttons (Space or Enter) that say their state (aria-pressed), a country opens with
 * Enter, and the search says what it found.
 */
import { useEffect, useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, Loader2, Plus, Search, X } from "lucide-react";
import { CompetitionLogo, CountryFlag, TeamLogo } from "@/components/football/Logos";
import { live } from "@/lib/api/v1/queries";
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/product/shared/States";
import {
  byCountry,
  chosenIn,
  full,
  hasLeague,
  hasTeam,
  leagueMatches,
  searchable,
  toggleLeague,
  toggleTeam,
  type Choice,
  type Limits,
} from "./model";

function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return settled;
}

/** The leagues a search lists at most (a country's name matches all of its leagues). */
const LEAGUE_RESULTS = 30;

const TOGGLE =
  "inline-flex min-h-11 max-w-full items-center gap-2 rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-45";

function Toggle({
  on,
  disabled,
  onClick,
  testId,
  children,
}: {
  on: boolean;
  disabled: boolean;
  onClick: () => void;
  testId: string;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      onClick={onClick}
      data-testid={testId}
      className={cn(
        TOGGLE,
        on
          ? "border-primary bg-primary/10 font-medium text-primary"
          : "border-border-strong bg-card text-foreground hover:bg-elevated",
      )}
    >
      {on ? (
        <Check aria-hidden className="h-4 w-4 shrink-0" />
      ) : (
        <Plus aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
      )}
      {children}
    </button>
  );
}

function LeagueName({ league }: { league: CompetitionBadge }) {
  return (
    <>
      <span aria-hidden className="contents">
        <CompetitionLogo src={league.logo_url} name={league.name} size={18} />
      </span>
      <span className="min-w-0 truncate">{league.name}</span>
    </>
  );
}

function TeamName({ team }: { team: TeamBadge }) {
  return (
    <>
      <span aria-hidden className="contents">
        <TeamLogo src={team.logo_url} name={team.name} size={18} />
      </span>
      <span className="min-w-0 truncate">{team.name}</span>
    </>
  );
}

interface Props {
  choice: Choice;
  limits: Limits;
  onChange: (next: Choice) => void;
}

/** The reader's choice: chips that remove with a tap, the counts against the limits. */
function Chosen({ choice, limits, onChange }: Props) {
  const none = choice.leagues.length + choice.teams.length === 0;
  const at = full(choice, limits);
  return (
    <section aria-labelledby="fav-chosen" data-testid="fav-chosen">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 id="fav-chosen" className="text-sm font-semibold">
          {t("onboarding.picker.chosen")}
        </h3>
        <p className="numeric text-caption text-muted-foreground" data-testid="fav-counts">
          {t("onboarding.picker.countLeagues", {
            count: choice.leagues.length,
            max: limits.leagues,
          })}
          {" · "}
          {t("onboarding.picker.countTeams", { count: choice.teams.length, max: limits.teams })}
        </p>
      </div>
      {none ? (
        <p className="mt-2 text-sm text-muted-foreground">{t("onboarding.picker.noneChosen")}</p>
      ) : (
        <ul className="mt-2 flex flex-wrap gap-2">
          {choice.leagues.map((l) => (
            <li key={`l${l.id}`} className="max-w-full">
              <button
                type="button"
                aria-label={t("onboarding.picker.remove", { name: l.name })}
                onClick={() => onChange(toggleLeague(choice, l, limits))}
                data-testid="fav-chip"
                data-kind="league"
                data-id={l.id}
                className={cn(TOGGLE, "border-primary/40 bg-primary/10 text-foreground")}
              >
                <LeagueName league={l} />
                <X aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </li>
          ))}
          {choice.teams.map((tm) => (
            <li key={`t${tm.id}`} className="max-w-full">
              <button
                type="button"
                aria-label={t("onboarding.picker.remove", { name: tm.name })}
                onClick={() => onChange(toggleTeam(choice, tm, limits))}
                data-testid="fav-chip"
                data-kind="team"
                data-id={tm.id}
                className={cn(TOGGLE, "border-primary/40 bg-primary/10 text-foreground")}
              >
                <TeamName team={tm} />
                <X aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {at.leagues ? (
        <p className="mt-2 text-caption text-warning" data-testid="fav-full-leagues">
          {t("onboarding.picker.fullLeagues", { max: limits.leagues })}
        </p>
      ) : null}
      {at.teams ? (
        <p className="mt-1 text-caption text-warning" data-testid="fav-full-teams">
          {t("onboarding.picker.fullTeams", { max: limits.teams })}
        </p>
      ) : null}
    </section>
  );
}

function LeagueToggles({
  leagues,
  choice,
  limits,
  onChange,
}: Props & { leagues: readonly CompetitionBadge[] }) {
  const atLimit = full(choice, limits).leagues;
  return (
    <ul className="flex flex-wrap gap-2">
      {leagues.map((l) => {
        const on = hasLeague(choice, l.id);
        return (
          <li key={l.id} className="max-w-full">
            <Toggle
              on={on}
              disabled={!on && atLimit}
              onClick={() => onChange(toggleLeague(choice, l, limits))}
              testId="fav-league"
            >
              <LeagueName league={l} />
            </Toggle>
          </li>
        );
      })}
    </ul>
  );
}

/** What a search found: the leagues (here, by name or country) and the teams (the API's). */
function Results({
  leagues,
  q,
  settled,
  choice,
  limits,
  onChange,
}: Props & { leagues: readonly CompetitionBadge[]; q: string; settled: string }) {
  const ready = searchable(settled);
  const found = useQuery({ ...live.favoriteOptions(settled), enabled: ready });
  const matching = leagues.filter((l) => leagueMatches(l, q)).slice(0, LEAGUE_RESULTS);
  const teams = ready ? (found.data?.teams ?? []) : [];
  const atLimit = full(choice, limits).teams;
  const pending = !ready || found.isFetching;
  let status: string;
  if (pending && matching.length === 0) status = t("onboarding.picker.searching");
  else if (matching.length + teams.length === 0) status = t("onboarding.picker.noneFound");
  else
    status = [
      t("onboarding.picker.foundLeagues", { count: matching.length }),
      pending
        ? t("onboarding.picker.searching")
        : t("onboarding.picker.found", { count: teams.length }),
    ].join(" · ");
  return (
    <div className="space-y-4" data-testid="fav-results">
      <p
        role="status"
        aria-live="polite"
        className="flex min-h-5 items-center gap-1 text-caption text-muted-foreground"
        data-testid="fav-status"
      >
        {pending ? <Loader2 aria-hidden className="h-3.5 w-3.5 animate-spin" /> : null}
        {status}
      </p>
      {matching.length > 0 ? (
        <section aria-label={t("onboarding.picker.leagues")} data-testid="fav-league-results">
          <h3 className="mb-1.5 text-sm font-semibold">{t("onboarding.picker.leagues")}</h3>
          <LeagueToggles leagues={matching} choice={choice} limits={limits} onChange={onChange} />
        </section>
      ) : null}
      {ready && found.isError ? (
        <ErrorState error={found.error} onRetry={() => void found.refetch()} />
      ) : null}
      {teams.length > 0 ? (
        <section aria-label={t("onboarding.picker.teams")} data-testid="fav-team-results">
          <h3 className="mb-1.5 text-sm font-semibold">{t("onboarding.picker.teams")}</h3>
          <ul className="flex flex-wrap gap-2">
            {teams.map((tm) => {
              const on = hasTeam(choice, tm.id);
              return (
                <li key={tm.id} className="max-w-full">
                  <Toggle
                    on={on}
                    disabled={!on && atLimit}
                    onClick={() => onChange(toggleTeam(choice, tm, limits))}
                    testId="fav-team"
                  >
                    <TeamName team={tm} />
                  </Toggle>
                </li>
              );
            })}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

/** Without a search: the leagues by country, each folded under its row (Colombia open), and how to find a team. */
function Browse({
  leagues,
  choice,
  limits,
  onChange,
}: Props & { leagues: readonly CompetitionBadge[] }) {
  return (
    <section aria-labelledby="fav-browse" data-testid="fav-leagues">
      <h3 id="fav-browse" className="text-sm font-semibold">
        {t("onboarding.picker.byCountry")}
      </h3>
      <div className="mt-2 divide-y divide-border rounded-xl border border-border">
        {byCountry(leagues).map((group) => {
          const name = group.country ?? t("onboarding.picker.international");
          const picked = chosenIn(choice, group.leagues);
          return (
            <details
              key={group.country ?? "-"}
              open={group.country === "Colombia"}
              className="group"
              data-testid="fav-country"
              data-country={group.country ?? ""}
            >
              <summary className="flex min-h-11 cursor-pointer list-none items-center gap-2 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                {group.country ? (
                  <span aria-hidden className="contents">
                    <CountryFlag
                      src={group.leagues[0]?.flag_url}
                      name={group.country}
                      height={12}
                    />
                  </span>
                ) : null}
                <span className="min-w-0 flex-1 truncate font-medium">{name}</span>
                <span className="shrink-0 text-caption text-muted-foreground">
                  {t("onboarding.picker.groupCount", { count: group.leagues.length })}
                  {picked > 0 ? ` · ${t("onboarding.picker.groupChosen", { count: picked })}` : ""}
                </span>
                <ChevronDown
                  aria-hidden
                  className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180"
                />
              </summary>
              <div className="px-3 pb-3 pt-1">
                <LeagueToggles
                  leagues={group.leagues}
                  choice={choice}
                  limits={limits}
                  onChange={onChange}
                />
              </div>
            </details>
          );
        })}
      </div>
      <p className="mt-2 text-caption text-muted-foreground">{t("onboarding.picker.teamsHint")}</p>
    </section>
  );
}

export function FavoritesPicker({ choice, limits, onChange }: Props) {
  const id = useId();
  const [text, setText] = useState("");
  const q = text.trim();
  const settled = useDebounced(q, 300);
  const options = useQuery(live.favoriteOptions(""));
  return (
    <div className="space-y-5" data-testid="favorites-picker">
      <Chosen choice={choice} limits={limits} onChange={onChange} />
      <div>
        <label htmlFor={`${id}-q`} className="block text-sm font-semibold">
          {t("onboarding.picker.searchLabel")}
        </label>
        <div className="relative mt-1.5">
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
          <input
            id={`${id}-q`}
            type="search"
            inputMode="search"
            autoComplete="off"
            enterKeyHint="search"
            value={text}
            maxLength={40}
            onChange={(e) => setText(e.currentTarget.value)}
            placeholder={t("onboarding.picker.searchPlaceholder")}
            data-testid="fav-search"
            className="h-11 w-full rounded-md border border-border-strong bg-background pl-9 pr-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>
      </div>
      {options.isPending ? (
        <p aria-busy="true" className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          {t("onboarding.picker.loading")}
        </p>
      ) : options.isError ? (
        <ErrorState error={options.error} onRetry={() => void options.refetch()} />
      ) : searchable(q) ? (
        <Results
          leagues={options.data.leagues}
          q={q}
          settled={settled}
          choice={choice}
          limits={limits}
          onChange={onChange}
        />
      ) : (
        <Browse
          leagues={options.data.leagues}
          choice={choice}
          limits={limits}
          onChange={onChange}
        />
      )}
    </div>
  );
}
