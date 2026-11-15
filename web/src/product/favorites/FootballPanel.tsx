/**
 * The profile's «Tu fútbol» (plan UX, A13 and section 21; inside its block of the account centre since B1): the
 * leagues and teams the reader follows - or the ones suggested for Colombia, labelled, while they chose none - and the
 * same picker as the welcome to change them. Saving replaces them exactly (the API refuses beyond the limits, it
 * never trims). They order Inicio; they never change a pick, a probability or a price.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, BellOff, Loader2, Pencil } from "lucide-react";
import { CompetitionTag, TeamLogo } from "@/components/football/Logos";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { FavoritesView } from "@/lib/api/v1/types_favorites";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { ErrorState, SkeletonCards } from "@/product/shared/States";
import { FavoritesPicker } from "./FavoritesPicker";
import { trackChanges } from "./analytics";
import { beforeOf, bodyOf, changes, choiceOf, limitsOf, type Choice } from "./model";

function Current({ view }: { view: FavoritesView }) {
  return (
    <div className="space-y-2" data-testid="football-current" data-suggested={view.suggested}>
      {view.suggested ? (
        <p className="text-sm text-muted-foreground">{t("onboarding.panel.suggested")}</p>
      ) : null}
      <ul className="flex flex-wrap gap-1.5">
        {view.leagues.map((c) => (
          <li
            key={`l${c.id}`}
            className="rounded-full border border-border bg-card px-2.5 py-1 text-caption"
          >
            <CompetitionTag
              name={c.name}
              logo={c.logo_url}
              flag={c.flag_url}
              country={c.country}
              size={12}
            />
          </li>
        ))}
        {view.teams.map((tm) => (
          <li
            key={`t${tm.id}`}
            className="flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-caption"
          >
            <span aria-hidden className="contents">
              <TeamLogo src={tm.logo_url} name={tm.name} size={12} />
            </span>
            {tm.name}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A bell per followed team (decision 8; sheet U02): the reader's own teams only, never the suggested ones. */
function TeamBells({ view }: { view: FavoritesView }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState<number | null>(null);
  const [failed, setFailed] = useState(false);
  if (view.suggested || view.teams.length === 0 || view.muted_teams === undefined) return null;
  const muted = new Set(view.muted_teams);
  async function toggle(teamId: number, notify: boolean) {
    setBusy(teamId);
    setFailed(false);
    try {
      qc.setQueryData(live.favorites.queryKey, await v1.setTeamBell(teamId, notify));
    } catch {
      setFailed(true);
    } finally {
      setBusy(null);
    }
  }
  return (
    <section aria-labelledby="team-bells" className="space-y-2" data-testid="team-bells">
      <h3 id="team-bells" className="text-sm font-semibold">
        {t("onboarding.panel.bellsTitle")}
      </h3>
      <p className="text-xs text-muted-foreground">{t("onboarding.panel.bellsHelp")}</p>
      <ul className="divide-y divide-border rounded-control border border-border">
        {view.teams.map((tm) => {
          const on = !muted.has(tm.id);
          return (
            <li key={tm.id} className="flex min-h-12 items-center gap-2.5 px-3 py-1.5">
              <span aria-hidden className="contents">
                <TeamLogo src={tm.logo_url} name={tm.name} size={20} />
              </span>
              <span className="min-w-0 flex-1 truncate text-sm">{tm.name}</span>
              <button
                type="button"
                aria-pressed={on}
                aria-label={t(on ? "onboarding.panel.bellOn" : "onboarding.panel.bellOff", {
                  name: tm.name,
                })}
                disabled={busy === tm.id}
                onClick={() => void toggle(tm.id, !on)}
                data-testid="team-bell"
                data-team={tm.id}
                className={cn(
                  "flex h-11 w-11 shrink-0 items-center justify-center rounded-field border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50",
                  on
                    ? "border-primary/40 bg-primary-soft text-primary"
                    : "border-border-strong bg-elevated text-muted-foreground",
                )}
              >
                {on ? (
                  <Bell aria-hidden className="h-[1.125rem] w-[1.125rem]" />
                ) : (
                  <BellOff aria-hidden className="h-[1.125rem] w-[1.125rem]" />
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {failed ? (
        <p role="alert" className="text-sm text-negative">
          {t("onboarding.panel.bellFailed")}
        </p>
      ) : null}
    </section>
  );
}

export function FootballPanel() {
  const qc = useQueryClient();
  const favorites = useQuery(live.favorites);
  const [editing, setEditing] = useState<Choice | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState(false);
  const [saved, setSaved] = useState(false);
  const view = favorites.data;

  async function save() {
    if (!editing || !view || busy) return;
    setBusy(true);
    setFailure(false);
    try {
      const next = await v1.saveFavorites(bodyOf(editing));
      const { added, removed } = changes(beforeOf(view), choiceOf(next));
      trackChanges({ added, removed });
      qc.setQueryData(live.favorites.queryKey, next);
      void qc.invalidateQueries({ queryKey: ["v1", "today"] });
      void qc.invalidateQueries({ queryKey: ["me", "account"] });
      void qc.invalidateQueries({ queryKey: ["me", "personal"] });
      setEditing(null);
      setSaved(true);
    } catch {
      setFailure(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="football-panel">
      <p className="mb-3 text-xs text-muted-foreground">{t("onboarding.panel.help")}</p>
      {favorites.isPending ? (
        <SkeletonCards count={2} />
      ) : favorites.isError || !view ? (
        <ErrorState error={favorites.error} onRetry={() => void favorites.refetch()} />
      ) : editing ? (
        <div className="space-y-4">
          <FavoritesPicker choice={editing} limits={limitsOf(view)} onChange={setEditing} />
          {failure ? (
            <p role="alert" className="text-sm text-negative" data-testid="football-error">
              {t("onboarding.panel.failed")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => void save()}
              disabled={busy}
              data-testid="football-save"
              className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
            >
              {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
              {t("onboarding.panel.save")}
            </button>
            <button
              type="button"
              onClick={() => {
                setEditing(null);
                setFailure(false);
              }}
              disabled={busy}
              className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-4 py-2 text-sm hover:bg-elevated"
            >
              {t("onboarding.panel.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <Current view={view} />
          <TeamBells view={view} />
          {saved ? (
            <p role="status" className="text-sm text-positive" data-testid="football-saved">
              {t("onboarding.panel.saved")}
            </p>
          ) : null}
          <button
            type="button"
            onClick={() => {
              setEditing(choiceOf(view));
              setSaved(false);
            }}
            data-testid="football-edit"
            className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-strong px-3 py-2 text-sm font-medium hover:bg-elevated"
          >
            <Pencil aria-hidden className="h-4 w-4" />
            {view.suggested ? t("onboarding.panel.choose") : t("onboarding.panel.edit")}
          </button>
        </div>
      )}
    </div>
  );
}
