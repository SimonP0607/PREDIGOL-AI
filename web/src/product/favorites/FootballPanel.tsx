/**
 * The profile's «Tu fútbol» (plan UX, A13 and section 21; inside its block of the account centre since B1): the
 * leagues and teams the reader follows - or the ones suggested for Colombia, labelled, while they chose none - and the
 * same picker as the welcome to change them. Saving replaces them exactly (the API refuses beyond the limits, it
 * never trims). They order Inicio; they never change a pick, a probability or a price.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil } from "lucide-react";
import { CompetitionTag, TeamLogo } from "@/components/football/Logos";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { FavoritesView } from "@/lib/api/v1/types_favorites";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { ErrorState } from "@/product/shared/States";
import { FavoritesPicker } from "./FavoritesPicker";
import { bodyOf, changes, choiceOf, limitsOf, type Choice } from "./model";

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
      const { added, removed } = changes(view.suggested ? null : choiceOf(view), choiceOf(next));
      for (const c of added) track("favorite_added", { kind: c.kind, id: c.id });
      for (const c of removed) track("favorite_removed", { kind: c.kind, id: c.id });
      qc.setQueryData(live.favorites.queryKey, next);
      void qc.invalidateQueries({ queryKey: ["v1", "today"] });
      void qc.invalidateQueries({ queryKey: ["me", "account"] });
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
        <Loader2 aria-hidden className="h-5 w-5 animate-spin text-muted-foreground" />
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
