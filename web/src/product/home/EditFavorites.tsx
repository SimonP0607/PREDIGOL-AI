/**
 * «Editar favoritos» (plan de Inicio, 3.4): the reader's favourites changed without leaving Inicio - a side sheet on a desktop,
 * a sheet from the bottom on a phone - with the very picker of the welcome and the profile (it is not modified: the welcome uses
 * it). Every change saves at once, replacing the choice exactly as the profile does; Inicio refreshes in place behind the sheet
 * - no reload, no change of page. Changes made while one is still being saved are sent after it, the last one winning.
 */
import { Link } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { FavoritesView } from "@/lib/api/v1/types_favorites";
import { t } from "@/lib/i18n";
import { FavoritesPicker } from "@/product/favorites/FavoritesPicker";
import { trackChanges } from "@/product/favorites/analytics";
import {
  beforeOf,
  bodyOf,
  changes,
  choiceOf,
  limitsOf,
  type Choice,
} from "@/product/favorites/model";
import { ErrorState, SkeletonCards } from "@/product/shared/States";
import { createSaver, type LatestSaver } from "./latestSaver";

type Saving = "idle" | "saving" | "saved" | "failed";

function Editor({ view }: { view: FavoritesView }) {
  const qc = useQueryClient();
  const [choice, setChoice] = useState<Choice>(() => choiceOf(view));
  const [state, setState] = useState<Saving>("idle");
  const saved = useRef<FavoritesView>(view);
  const saver = useRef<LatestSaver<Choice> | null>(null);
  saver.current ??= createSaver((next: Choice) => v1.saveFavorites(bodyOf(next)), {
    onStart: () => setState("saving"),
    onSaved: (answer) => {
      const { added, removed } = changes(beforeOf(saved.current), choiceOf(answer));
      trackChanges({ added, removed });
      saved.current = answer;
      qc.setQueryData(live.favorites.queryKey, answer);
    },
    onIdle: () => {
      // Inicio's own answers depend on the favourites: they are asked again, in place.
      void qc.invalidateQueries({ queryKey: ["v1", "today"] });
      void qc.invalidateQueries({ queryKey: ["me", "account"] });
      void qc.invalidateQueries({ queryKey: ["me", "personal"] });
      setState("saved");
    },
    onFail: () => setState("failed"),
  });

  function onChange(next: Choice) {
    setChoice(next);
    saver.current?.push(next);
  }

  return (
    <div className="mt-4 space-y-4" data-testid="edit-favorites-body">
      <FavoritesPicker choice={choice} limits={limitsOf(view)} onChange={onChange} />
      <div className="min-h-6 text-sm" aria-live="polite">
        {state === "saving" ? (
          <p
            className="flex items-center gap-2 text-muted-foreground"
            data-testid="edit-favorites-saving"
          >
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
            {t("home.editFavorites.saving")}
          </p>
        ) : null}
        {state === "saved" ? (
          <p role="status" className="text-positive" data-testid="edit-favorites-saved">
            {t("home.editFavorites.saved")}
          </p>
        ) : null}
        {state === "failed" ? (
          <p role="alert" className="text-negative" data-testid="edit-favorites-error">
            {t("home.editFavorites.failed")}{" "}
            <button
              type="button"
              onClick={() => saver.current?.retry()}
              className="tap-y relative font-medium underline"
            >
              {t("home.editFavorites.retry")}
            </button>
          </p>
        ) : null}
      </div>
      <Link
        to="/profile"
        hash="football"
        className="tap-y relative inline-flex text-sm font-medium text-primary hover:underline"
      >
        {t("home.editFavorites.profile")}
      </Link>
    </div>
  );
}

function Body() {
  const favorites = useQuery(live.favorites);
  const view = favorites.data;
  // An editor that is already open keeps its own choice: the answers its saves put in the cache do not reset it.
  const [first, setFirst] = useState<FavoritesView | null>(null);
  useEffect(() => {
    if (view && !first) setFirst(view);
  }, [view, first]);
  if (favorites.isPending) return <SkeletonCards count={2} />;
  if (favorites.isError || !first) {
    return <ErrorState error={favorites.error} onRetry={() => void favorites.refetch()} />;
  }
  return <Editor view={first} />;
}

/** The «Editar favoritos» action of «Para ti» and the sheet it opens. */
export function EditFavorites() {
  const mobile = useIsMobile();
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <button
          type="button"
          data-testid="layer-edit"
          className="relative inline-flex min-h-11 shrink-0 items-center gap-1 rounded-md px-2.5 text-sm font-medium text-primary hover:bg-primary/10"
        >
          <Pencil aria-hidden className="h-3.5 w-3.5" />
          {t("home.layers.edit")}
        </button>
      </SheetTrigger>
      <SheetContent
        side={mobile ? "bottom" : "right"}
        closeLabel={t("home.editFavorites.close")}
        data-testid="edit-favorites"
        className={
          mobile
            ? "max-h-[88dvh] overflow-y-auto rounded-t-2xl px-4 pb-[calc(1.5rem+env(safe-area-inset-bottom))] pt-5"
            : "w-full overflow-y-auto sm:max-w-md"
        }
      >
        <SheetHeader>
          <SheetTitle>{t("home.editFavorites.title")}</SheetTitle>
          <SheetDescription>{t("home.editFavorites.description")}</SheetDescription>
        </SheetHeader>
        {open ? <Body /> : null}
      </SheetContent>
    </Sheet>
  );
}
