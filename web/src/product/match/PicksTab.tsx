/**
 * The picks of a match (REVIEW PREDIGOL, point 4; plan UX, A9: in the Resumen before and during the match - the published
 * ones with their state - and in the Postpartido once it is over).
 *
 * before kick-off  every qualified pick of the match, the best value first, in pages of 15 - only when there is one
 *                  (inside PrediGol Intelligence, plan Partidos y Match Center, R2-R3);
 * after kick-off   the picks PrediGol made before it, as they were taken, with what the match is doing and,
 *                  at the end, their result (En juego / Ganado / Perdido) - never re-priced;
 * finished         and, for the admin, the AI's post-mortem of each one.
 */
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { History, ShieldCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { PostmortemCard } from "@/live/PostmortemsPanel";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { ShadowBadge } from "@/product/shared/Bits";
import { Pager } from "@/product/shared/Pager";
import { usePaged } from "@/product/shared/paging";
import { PickCard } from "@/product/shared/PickCard";
import type { PickCard as PickCardData } from "@/lib/api/v1/types_product";
import { SelectablePriceRow } from "@/product/odds/SelectablePrice";
import { pickableOfCard } from "@/product/records/pickable";
import { StartedPickCard } from "@/product/shared/StartedPickCard";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { matchPicks, outcomeCounts, useMatchPicks } from "./picks";
import { Block, SectionNote } from "./ui";
import { PickAnchor, useFocusedPick } from "./pickFocus";

export type UpcomingPicksLoad =
  | { status: "pending" }
  | { status: "error"; error: unknown; retry?: (() => void) | undefined }
  | {
      status: "success";
      /** This match's picks on the board, the best value first. */
      picks: PickCardData[];
      /** The owner's shadow preview: the picks in evaluation, labelled as such. */
      shadow: boolean;
      /** The board's own ranking (its «top»), for each pick's number. */
      top: readonly PickCardData[];
    };

/**
 * The picks of a match before kick-off, inside PrediGol Intelligence (plan Partidos y Match Center, R2-R3): the ones PrediGol
 * published, and ONLY when there is one - no picks is no block and no notice (a reader is never told that selections are in
 * evaluation). With the owner's shadow preview on, the picks in evaluation, each labelled. Apart from the query, so that a
 * test can render it with a stub card.
 */
export function UpcomingPicksView({
  load,
  resetKey,
  renderPick,
  focused = null,
}: {
  load: UpcomingPicksLoad;
  resetKey: string;
  renderPick: (
    pick: PickCardData,
    rank: number | undefined,
    shadow: boolean,
    focused: boolean,
  ) => ReactNode;
  /** The pick a link names («Más sobre este pick», `?pick=`): brought into view, marked, its why opened. */
  focused?: number | null;
}) {
  const picks = load.status === "success" ? load.picks : [];
  const shadow = load.status === "success" && load.shadow;
  const paged = usePaged(picks, `${resetKey}|${shadow}`);
  if (load.status === "pending") {
    return (
      <div aria-busy="true" aria-label={t("common.loading")} data-testid="match-picks-loading">
        <SkeletonBlock className="h-24" />
      </div>
    );
  }
  if (load.status === "error") {
    return <ErrorState error={load.error} onRetry={load.retry} className="py-4" />;
  }
  if (picks.length === 0) {
    // The owner's preview says the board was looked at; a reader gets nothing at all.
    return shadow ? <SectionNote>{t("match.picks.noneShadow")}</SectionNote> : null;
  }
  const rankOf = new Map(load.top.map((p, i) => [p.pick_id, i + 1]));
  return (
    <section
      aria-label={shadow ? t("match.intelligence.picksShadow") : t("match.intelligence.picks")}
      data-testid="match-picks"
      data-shadow={shadow ? "true" : "false"}
      className={cn("space-y-3 rounded-lg", shadow && "border border-info/40 p-3")}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-caption font-semibold uppercase tracking-[0.08em] text-muted-foreground">
          {shadow ? t("match.intelligence.picksShadow") : t("match.intelligence.picks")}
        </h3>
        {shadow ? <ShadowBadge compact /> : null}
      </div>
      {shadow ? null : (
        <p className="text-caption text-muted-foreground">{t("match.picksTab.intro")}</p>
      )}
      <div className="grid gap-3 md:grid-cols-2">
        {paged.items.map((p) => (
          <PickAnchor key={p.pick_id} pickId={p.pick_id} focused={focused === p.pick_id}>
            {renderPick(p, rankOf.get(p.pick_id), shadow, focused === p.pick_id)}
          </PickAnchor>
        ))}
      </div>
      <Pager paged={paged} />
    </section>
  );
}

/** The match's picks before kick-off, from the picks board (`/picks`), as PrediGol Intelligence shows them. */
export function UpcomingPicks({ ctx }: { ctx: MatchCtx }) {
  const q = useMatchPicks(ctx);
  const focused = useFocusedPick();
  const board = q.data?.data;
  const load: UpcomingPicksLoad = q.isPending
    ? { status: "pending" }
    : q.isError
      ? { status: "error", error: q.error, retry: () => void q.refetch() }
      : {
          status: "success",
          picks: matchPicks(board, Number(ctx.fixtureId)),
          shadow: board?.source === "shadow_preview",
          top: board?.top ?? [],
        };
  return (
    <UpcomingPicksView
      load={load}
      resetKey={ctx.fixtureId}
      focused={focused}
      renderPick={(p, rank, shadow, isFocused) => (
        <PickCard
          pick={p}
          rank={rank}
          shadow={shadow}
          autoOpenWhy={isFocused}
          actions={<SelectablePriceRow sel={pickableOfCard(p)} />}
        />
      )}
    />
  );
}

function Taken({ ctx, why }: { ctx: MatchCtx; why?: ((pickId: number) => ReactNode) | undefined }) {
  const q = useMatchPicks(ctx);
  const board = q.data?.data;
  const shadow = board?.source === "shadow_preview";
  const picks = (board?.started ?? []).filter((p) => p.fixture_id === Number(ctx.fixtureId));
  const focused = useFocusedPick();
  const paged = usePaged(picks, `${ctx.fixtureId}|${shadow}`);
  const c = outcomeCounts(picks);
  return (
    <Block
      title={t("match.picksTab.takenTitle")}
      icon={<History />}
      right={shadow ? <ShadowBadge /> : null}
      className={cn(shadow && "border-info/40")}
    >
      {q.isPending ? (
        <SkeletonBlock className="h-40" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-5" />
      ) : picks.length === 0 ? (
        <SectionNote>{t("match.picks.noneStarted")}</SectionNote>
      ) : (
        <div className="space-y-3" data-testid="prematch-picks">
          <p className="text-caption text-muted-foreground">{t("match.picks.prematchHelp")}</p>
          <p className="numeric text-xs font-medium" data-testid="picks-outcome">
            {t("match.picksTab.outcome", { won: c.won, lost: c.lost, open: c.open, void: c.void })}
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            {paged.items.map((p) => (
              <PickAnchor key={p.pick_id} pickId={p.pick_id} focused={focused === p.pick_id}>
                <StartedPickCard
                  pick={p}
                  shadow={shadow}
                  autoOpenWhy={focused === p.pick_id}
                  footer={why?.(p.pick_id)}
                />
              </PickAnchor>
            ))}
          </div>
          <Pager paged={paged} />
        </div>
      )}
    </Block>
  );
}

/** The admin's view of why each pick of the match won or lost (ai.pick_postmortems). */
function Postmortems({ ctx }: { ctx: MatchCtx }) {
  const q = useQuery(live.aiPostmortems({ fixture_id: Number(ctx.fixtureId) }));
  const rows = q.data?.data ?? [];
  return (
    <Block
      title={t("match.picksTab.postmortems")}
      icon={<ShieldCheck />}
      right={<span className="text-caption text-info">{t("match.picksTab.postmortemsAdmin")}</span>}
      className="border-info/30"
    >
      {q.isPending ? (
        <SkeletonBlock className="h-24" />
      ) : q.isError ? (
        <ApiErrorNotice error={q.error} />
      ) : rows.length === 0 ? (
        <SectionNote>{t("match.picksTab.postmortemsNone")}</SectionNote>
      ) : (
        <ul className="space-y-2" data-testid="match-postmortems">
          {rows.map((pm) => (
            <PostmortemCard key={pm.id} pm={pm} />
          ))}
        </ul>
      )}
    </Block>
  );
}

/**
 * ``why``: in the Postpartido, what each pick taken before kick-off gets under its card - how it ended and the facts of the match
 * behind it (plan UX, B4).
 */
export function PicksTab({
  ctx,
  why,
}: {
  ctx: MatchCtx;
  why?: ((pickId: number) => ReactNode) | undefined;
}) {
  if (ctx.phase === "scheduled") return <UpcomingPicks ctx={ctx} />;
  return (
    <div className="space-y-4">
      <Taken ctx={ctx} why={why} />
      {ctx.showAdmin && ctx.phase === "finished" ? <Postmortems ctx={ctx} /> : null}
    </div>
  );
}
