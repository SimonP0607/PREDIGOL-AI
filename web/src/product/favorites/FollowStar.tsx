/**
 * The star beside a team in a match's header (plan UX, A13: «estrella para seguir a un equipo»): follows the team or stops
 * following it, in one tap, for a reader's account. While the reader has chosen no favourites, following a team keeps the
 * suggested ones they already saw on Inicio and adds the team - nothing they had disappears. At the limit (20 teams) the
 * tap says so and changes nothing. It orders Inicio; it never changes a pick, a probability or a price.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { TeamBadge } from "@/lib/api/v1/types_product";
import { t } from "@/lib/i18n";
import { track } from "@/lib/track";
import { cn } from "@/lib/utils";
import { usePushMoment } from "@/product/push/moments";
import { bodyOf, changes, choiceOf, hasTeam, limitsOf, toggleTeam } from "./model";

export function FollowStar({ team }: { team: TeamBadge }) {
  const auth = useAuth();
  const qc = useQueryClient();
  const reader = auth.user?.role === "USER";
  const favorites = useQuery({ ...live.favorites, enabled: reader });
  const [busy, setBusy] = useState(false);
  const pushMoment = usePushMoment();
  const view = favorites.data;
  if (!reader || !view || !view.personalization) return null;
  const following = !view.suggested && hasTeam(choiceOf(view), team.id);

  async function flip() {
    if (!view || busy) return;
    const before = choiceOf(view);
    const limits = limitsOf(view);
    if (!following && before.teams.length >= limits.teams && !hasTeam(before, team.id)) {
      toast(t("onboarding.follow.full", { max: limits.teams, team: team.name }));
      return;
    }
    const next = following || !hasTeam(before, team.id) ? toggleTeam(before, team, limits) : before; // a suggested team made the reader's own as it is
    setBusy(true);
    try {
      const saved = await v1.saveFavorites(bodyOf(next));
      const { added, removed } = changes(view.suggested ? null : before, choiceOf(saved));
      for (const c of added) track("favorite_added", { kind: c.kind, id: c.id });
      for (const c of removed) track("favorite_removed", { kind: c.kind, id: c.id });
      qc.setQueryData(live.favorites.queryKey, saved);
      void qc.invalidateQueries({ queryKey: ["v1", "today"] });
      void qc.invalidateQueries({ queryKey: ["me", "personal"] });
      toast(
        t(following ? "onboarding.follow.removed" : "onboarding.follow.added", { team: team.name }),
      );
      // Plan UX, B7: following a team is a moment to offer its line-ups' notices (never on opening)
      if (!following) pushMoment({ reason: "follow", team: team.name });
    } catch {
      toast(t("onboarding.follow.failed"));
    } finally {
      setBusy(false);
    }
  }

  const label = t(following ? "onboarding.follow.remove" : "onboarding.follow.add", {
    team: team.name,
  });
  return (
    <button
      type="button"
      aria-pressed={following}
      aria-label={label}
      title={label}
      disabled={busy}
      onClick={() => void flip()}
      data-testid="follow-star"
      data-team={team.id}
      className={cn(
        "tap relative inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
        following
          ? "border-gold/60 bg-gold-soft text-gold-strong"
          : "border-border-strong bg-card text-muted-foreground hover:text-foreground",
      )}
    >
      <Star aria-hidden className={cn("h-4 w-4", following && "fill-current")} />
    </button>
  );
}
