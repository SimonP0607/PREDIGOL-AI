/**
 * «¿Agregas la Serie A a tus ligas?» (plan UX, B2; section 38: «sugerencias con confirmación»): one league or team the
 * reader keeps opening outside what they follow - three matches or more on two days or more in the last 30 (GET
 * /me/personal) -, with its reason and two buttons. «Agregar» saves their favourites with it (the suggested ones too while
 * they chose none: nothing they had disappears); «No, gracias» means it never comes back. Nothing is followed without the
 * tap, and the card is never shown to the owner's console account or with personalisation off.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Lightbulb } from "lucide-react";
import { toast } from "sonner";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { Suggestion } from "@/lib/api/v1/types_personal";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { bodyOf, changes, choiceOf, withSuggestion } from "./model";

export function SuggestionCard() {
  const auth = useAuth();
  const reader = auth.user?.role === "USER";
  const qc = useQueryClient();
  const personal = useQuery({ ...live.personal, enabled: reader });
  const favorites = useQuery({ ...live.favorites, enabled: reader });
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const s = personal.data?.suggestion ?? null;
  const view = favorites.data;
  if (!reader || !s || !view || !personal.data?.personalization || !view.personalization)
    return null;

  async function add(suggestion: Suggestion) {
    if (!view || busy) return;
    setBusy(true);
    setFailed(false);
    try {
      const before = view.suggested ? null : choiceOf(view);
      const saved = await v1.saveFavorites(bodyOf(withSuggestion(view, suggestion)));
      const { added, removed } = changes(before, choiceOf(saved));
      for (const c of added) track("favorite_added", { kind: c.kind, id: c.id });
      for (const c of removed) track("favorite_removed", { kind: c.kind, id: c.id });
      qc.setQueryData(live.favorites.queryKey, saved);
      void qc.invalidateQueries({ queryKey: ["v1", "today"] });
      void qc.invalidateQueries({ queryKey: ["me", "personal"] });
      void qc.invalidateQueries({ queryKey: ["me", "account"] });
      toast(t("home.suggest.added", { name: suggestion.name }));
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  async function dismiss(suggestion: Suggestion) {
    if (busy) return;
    setBusy(true);
    setFailed(false);
    try {
      qc.setQueryData(
        live.personal.queryKey,
        await v1.dismissSuggestion(suggestion.kind, suggestion.id),
      );
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-labelledby="suggestion-title"
      data-testid="suggestion-card"
      data-kind={s.kind}
      data-id={s.id}
      className="mt-3 rounded-xl border border-primary/30 bg-primary/5 p-3 sm:p-4"
    >
      <div className="flex items-start gap-3">
        <Lightbulb aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
        <div className="min-w-0 flex-1 space-y-1">
          <h3 id="suggestion-title" className="break-words text-sm font-semibold">
            {t(s.kind === "league" ? "home.suggest.titleLeague" : "home.suggest.titleTeam", {
              name: s.name,
            })}
          </h3>
          <p className="text-xs text-muted-foreground" data-testid="suggestion-reason">
            {t("home.suggest.reason", { count: s.matches })}
          </p>
          <p className="text-caption text-subtle-foreground">{t("home.suggest.rule")}</p>
          {failed ? (
            <p role="alert" className="text-caption text-destructive">
              {t("home.suggest.failed")}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2 pt-1.5">
            <button
              type="button"
              disabled={busy}
              onClick={() => void add(s)}
              data-testid="suggestion-add"
              className="tap-y relative inline-flex min-h-9 items-center rounded-full bg-primary px-4 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 pointer-coarse:min-h-11"
            >
              {t("home.suggest.add")}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => void dismiss(s)}
              data-testid="suggestion-dismiss"
              className="tap-y relative inline-flex min-h-9 items-center rounded-full border border-border-strong px-4 text-xs font-medium transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 pointer-coarse:min-h-11"
            >
              {t("home.suggest.dismiss")}
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
