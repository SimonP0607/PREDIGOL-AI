/**
 * Choosing the leagues and teams a reader follows (plan UX, A13; section 20): the welcome's «Tu fútbol» and the profile's
 * own card. A phone first: the reader's choice on top as chips that remove with a tap, a search for teams (two letters or
 * more, without accents or case - the API's own folding), and every league PrediGol follows as toggles grouped by country
 * (Colombia first), every target 44 px. The limits show before the reader reaches them; at a limit nothing more is added.
 * A keyboard reaches everything: the toggles are buttons (Space or Enter) with their state said (aria-pressed), and the
 * search says how many teams it found.
 */
import { useEffect, useId, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, Loader2, Plus, Search, X } from "lucide-react";
import { CompetitionLogo, CountryFlag, TeamLogo } from "@/components/football/Logos";
import { live } from "@/lib/api/v1/queries";
import type { CompetitionBadge, TeamBadge } from "@/lib/api/v1/types_product";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { ErrorState } from "@/product/shared/States";
import {
  byCountry,
  full,
  hasLeague,
  hasTeam,
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

/** The reader's choice: chips that remove with a tap, the counts against the limits. */
function Chosen({
  choice,
  limits,
  onChange,
}: {
  choice: Choice;
  limits: Limits;
  onChange: (next: Choice) => void;
}) {
  const none = choice.leagues.length + choice.teams.length === 0;
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
    </section>
  );
}

/** Teams by name: two letters or more, the API's results as toggles, how many it found said to a screen reader. */
function TeamSearch({
  choice,
  limits,
  onChange,
}: {
  choice: Choice;
  limits: Limits;
  onChange: (next: Choice) => void;
}) {
  const id = useId();
  const [text, setText] = useState("");
  const settled = useDebounced(text.trim(), 300);
  const ready = searchable(settled);
  const found = useQuery({ ...live.favoriteOptions(settled), enabled: ready });
  const teams = ready ? (found.data?.teams ?? []) : [];
  const atLimit = full(choice, limits).teams;
  let status = "";
  if (ready && found.isFetching) status = t("onboarding.picker.searching");
  else if (ready && found.data)
    status =
      teams.length > 0
        ? t("onboarding.picker.found", { count: teams.length })
        : t("onboarding.picker.noTeams");
  return (
    <section aria-labelledby={`${id}-teams`} data-testid="fav-teams">
      <h3 id={`${id}-teams`} className="text-sm font-semibold">
        {t("onboarding.picker.teams")}
      </h3>
      <label htmlFor={`${id}-q`} className="mt-2 block text-caption text-muted-foreground">
        {t("onboarding.picker.searchLabel")}
      </label>
      <div className="relative mt-1">
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
      <p
        role="status"
        aria-live="polite"
        className="mt-1.5 min-h-5 text-caption text-muted-foreground"
      >
        {ready && found.isFetching ? (
          <Loader2 aria-hidden className="mr-1 inline h-3.5 w-3.5 animate-spin" />
        ) : null}
        {status}
      </p>
      {ready && found.isError ? (
        <ErrorState error={found.error} onRetry={() => void found.refetch()} />
      ) : null}
      {teams.length > 0 ? (
        <ul className="mt-1 flex flex-wrap gap-2" data-testid="fav-team-results">
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
      ) : null}
      {atLimit ? (
        <p className="mt-2 text-caption text-warning" data-testid="fav-full-teams">
          {t("onboarding.picker.fullTeams", { max: limits.teams })}
        </p>
      ) : null}
    </section>
  );
}

/** Every league PrediGol follows, by country, as toggles. */
function Leagues({
  choice,
  limits,
  onChange,
}: {
  choice: Choice;
  limits: Limits;
  onChange: (next: Choice) => void;
}) {
  const id = useId();
  const options = useQuery(live.favoriteOptions(""));
  const atLimit = full(choice, limits).leagues;
  return (
    <section aria-labelledby={`${id}-leagues`} data-testid="fav-leagues">
      <h3 id={`${id}-leagues`} className="text-sm font-semibold">
        {t("onboarding.picker.leagues")}
      </h3>
      {atLimit ? (
        <p className="mt-1 text-caption text-warning" data-testid="fav-full-leagues">
          {t("onboarding.picker.fullLeagues", { max: limits.leagues })}
        </p>
      ) : null}
      {options.isPending ? (
        <p aria-busy="true" className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          {t("onboarding.picker.loading")}
        </p>
      ) : options.isError ? (
        <ErrorState error={options.error} onRetry={() => void options.refetch()} />
      ) : (
        <div className="mt-2 space-y-3">
          {byCountry(options.data.leagues).map((group) => (
            <div
              key={group.country ?? "-"}
              role="group"
              aria-label={group.country ?? t("onboarding.picker.international")}
            >
              <p className="mb-1.5 flex items-center gap-1.5 text-caption font-medium uppercase tracking-[0.06em] text-muted-foreground">
                {group.country ? (
                  <span aria-hidden className="contents">
                    <CountryFlag
                      src={group.leagues[0]?.flag_url}
                      name={group.country}
                      height={10}
                    />
                  </span>
                ) : null}
                {group.country ?? t("onboarding.picker.international")}
              </p>
              <ul className="flex flex-wrap gap-2">
                {group.leagues.map((l) => {
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
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

export function FavoritesPicker({
  choice,
  limits,
  onChange,
}: {
  choice: Choice;
  limits: Limits;
  onChange: (next: Choice) => void;
}) {
  return (
    <div className="space-y-6" data-testid="favorites-picker">
      <Chosen choice={choice} limits={limits} onChange={onChange} />
      <TeamSearch choice={choice} limits={limits} onChange={onChange} />
      <Leagues choice={choice} limits={limits} onChange={onChange} />
    </div>
  );
}
