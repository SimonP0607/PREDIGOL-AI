/**
 * Following a player or a market from where the reader meets them (closing plan 3.1): «Seguir» in a player's card (a
 * line-up, an absence) and in a match's «Mercados». One tap follows or stops following, for a reader's account; the
 * leagues and teams they follow are sent as they are (and none while the ones they see are the suggested: a tap on a
 * player never makes the suggested leagues theirs). At the limit (20 players, 5 markets) the tap says so and changes
 * nothing. It only keeps the favourite; it never changes a pick, a probability or a price.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { MarketKey } from "@/lib/api/v1/types_records";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useJustChanged } from "@/product/shared/motion";
import { marketName } from "@/product/shared/markets";
import { trackChanges } from "./analytics";
import { catalogKeyName } from "./catalogName";
import {
  beforeOf,
  changes,
  choiceOf,
  extrasBody,
  hasCatalog,
  hasMarket,
  hasPlayer,
  limitsOf,
  toggleCatalog,
  toggleMarket,
  togglePlayer,
  type Choice,
} from "./model";

const BUTTON =
  "inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium motion-press focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";

function FollowButton({
  following,
  busy,
  label,
  onClick,
  testId,
  data,
}: {
  following: boolean;
  busy: boolean;
  label: string;
  onClick: () => void;
  testId: string;
  data: string;
}) {
  const saved = useJustChanged(following);
  return (
    <button
      type="button"
      aria-pressed={following}
      aria-label={label}
      title={label}
      disabled={busy}
      onClick={onClick}
      data-testid={testId}
      data-id={data}
      className={cn(
        BUTTON,
        following
          ? "border-gold/60 bg-gold-soft text-gold-strong"
          : "border-border-strong bg-card text-muted-foreground hover:text-foreground",
      )}
    >
      <Star
        aria-hidden
        className={cn("h-4 w-4", following && "fill-current", saved && "motion-pop")}
      />
      {following ? t("onboarding.follow.following") : t("onboarding.follow.follow")}
    </button>
  );
}

/** What both buttons share: the reader's favourites, the save with the analytics and the caches it refreshes. */
function useFollowing() {
  const auth = useAuth();
  const qc = useQueryClient();
  const reader = auth.user?.role === "USER";
  const favorites = useQuery({ ...live.favorites, enabled: reader });
  const [busy, setBusy] = useState(false);
  const view = favorites.data;
  const ready = reader && view !== undefined && view.personalization;

  async function save(next: Choice, done: string): Promise<void> {
    if (!view || busy) return;
    setBusy(true);
    try {
      const saved = await v1.saveFavorites(extrasBody(view, next));
      trackChanges(changes(beforeOf(view), choiceOf(saved)));
      qc.setQueryData(live.favorites.queryKey, saved);
      void qc.invalidateQueries({ queryKey: ["v1", "today"] });
      void qc.invalidateQueries({ queryKey: ["me", "personal"] });
      toast(done);
    } catch {
      toast(t("onboarding.follow.failed"));
    } finally {
      setBusy(false);
    }
  }
  return { view: ready ? view : undefined, busy, save };
}

/** «Seguir» in a player's card; nothing for a player PrediGol cannot name (no id) or for anyone but a reader. */
export function FollowPlayer({ id, name }: { id: number | null; name: string }) {
  const { view, busy, save } = useFollowing();
  if (!view || id === null) return null;
  const before = choiceOf(view);
  const following = hasPlayer(before, id);
  const limits = limitsOf(view);

  function flip() {
    if (id === null) return;
    if (!following && before.players.length >= limits.players) {
      toast(t("onboarding.follow.playerFull", { max: limits.players, name }));
      return;
    }
    const badge = { id, name, position: null, team: null };
    void save(
      togglePlayer(before, badge, limits),
      t(following ? "onboarding.follow.playerRemoved" : "onboarding.follow.playerAdded", { name }),
    );
  }

  return (
    <FollowButton
      following={following}
      busy={busy}
      label={t(following ? "onboarding.follow.playerRemove" : "onboarding.follow.playerAdd", {
        name,
      })}
      onClick={flip}
      testId="follow-player"
      data={String(id)}
    />
  );
}

/** «Seguir» in a match's «Mercados», beside the market's name. */
export function FollowMarket({ market }: { market: MarketKey }) {
  const { view, busy, save } = useFollowing();
  if (!view) return null;
  const before = choiceOf(view);
  const following = hasMarket(before, market);
  const limits = limitsOf(view);
  const name = marketName(market);

  function flip() {
    if (!following && before.markets.length >= limits.markets) {
      toast(t("onboarding.follow.marketFull", { max: limits.markets, market: name }));
      return;
    }
    void save(
      toggleMarket(before, market, limits),
      t(following ? "onboarding.follow.marketRemoved" : "onboarding.follow.marketAdded", {
        market: name,
      }),
    );
  }

  return (
    <FollowButton
      following={following}
      busy={busy}
      label={t(following ? "onboarding.follow.marketRemove" : "onboarding.follow.marketAdd", {
        market: name,
      })}
      onClick={flip}
      testId="follow-market"
      data={market}
    />
  );
}

/**
 * «Seguir» in a market of the catalogue that is not one of the five (CUOTAS, BE-025): the key the catalogue gives it is
 * what is kept. Only the reader's order of the markets they see changes; never a price.
 */
export function FollowCatalogMarket({ catalogKey }: { catalogKey: string }) {
  const { view, busy, save } = useFollowing();
  if (!view) return null;
  const before = choiceOf(view);
  const following = hasCatalog(before, catalogKey);
  const limits = limitsOf(view);
  const name = catalogKeyName(catalogKey);

  function flip() {
    if (!following && before.catalog.length >= limits.catalog) {
      toast(t("onboarding.follow.catalogFull", { max: limits.catalog, market: name }));
      return;
    }
    void save(
      toggleCatalog(before, catalogKey, limits),
      t(following ? "onboarding.follow.marketRemoved" : "onboarding.follow.marketAdded", {
        market: name,
      }),
    );
  }

  return (
    <FollowButton
      following={following}
      busy={busy}
      label={t(following ? "onboarding.follow.marketRemove" : "onboarding.follow.marketAdd", {
        market: name,
      })}
      onClick={flip}
      testId="follow-catalog-market"
      data={catalogKey}
    />
  );
}
