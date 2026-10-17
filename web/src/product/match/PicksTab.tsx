/**
 * Picks, a module of its own (REVIEW PREDIGOL, point 4: a match has many picks and they crowded the Resumen).
 *
 * before kick-off  every qualified pick of the match, the best value first, in pages of 15;
 * after kick-off   the picks PrediGol made before it, as they were taken, with what the match is doing and,
 *                  at the end, their result (En juego / Ganado / Perdido) - never re-priced;
 * finished         and, for the admin, the AI's post-mortem of each one.
 */
import { useQuery } from "@tanstack/react-query";
import { History, ShieldCheck, Target } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { live } from "@/lib/api/v1/queries";
import { PostmortemCard } from "@/live/AiResearchLive";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { ShadowBadge } from "@/product/shared/Bits";
import { Pager } from "@/product/shared/Pager";
import { usePaged } from "@/product/shared/paging";
import { PickCard } from "@/product/shared/PickCard";
import { SelectablePriceRow } from "@/product/odds/SelectablePrice";
import { pickableOfCard } from "@/product/records/pickable";
import { StartedPickCard } from "@/product/shared/StartedPickCard";
import { ErrorState, SkeletonBlock } from "@/product/shared/States";
import type { MatchCtx } from "./context";
import { matchPicks, outcomeCounts, useMatchPicks } from "./picks";
import { Block, SectionNote } from "./ui";

function Upcoming({ ctx }: { ctx: MatchCtx }) {
  const q = useMatchPicks(ctx);
  const board = q.data?.data;
  const shadow = board?.source === "shadow_preview";
  const picks = matchPicks(board, Number(ctx.fixtureId));
  const rankOf = new Map((board?.top ?? []).map((p, i) => [p.pick_id, i + 1]));
  const paged = usePaged(picks, `${ctx.fixtureId}|${shadow}`);
  return (
    <Block
      title={t("match.picksTab.title")}
      icon={<Target />}
      right={shadow ? <ShadowBadge /> : null}
      className={cn(shadow && "border-info/40")}
    >
      {q.isPending ? (
        <SkeletonBlock className="h-40" />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} className="py-5" />
      ) : picks.length === 0 ? (
        <SectionNote>{shadow ? t("match.picks.noneShadow") : t("match.picks.none")}</SectionNote>
      ) : (
        <div className="space-y-3" data-testid="match-picks">
          <p className="text-caption text-muted-foreground">{t("match.picksTab.intro")}</p>
          <div className="grid gap-3 md:grid-cols-2">
            {paged.items.map((p) => (
              <PickCard
                key={p.pick_id}
                pick={p}
                rank={rankOf.get(p.pick_id)}
                shadow={shadow}
                actions={<SelectablePriceRow sel={pickableOfCard(p)} />}
              />
            ))}
          </div>
          <Pager paged={paged} />
        </div>
      )}
    </Block>
  );
}

function Taken({ ctx }: { ctx: MatchCtx }) {
  const q = useMatchPicks(ctx);
  const board = q.data?.data;
  const shadow = board?.source === "shadow_preview";
  const picks = (board?.started ?? []).filter((p) => p.fixture_id === Number(ctx.fixtureId));
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
              <StartedPickCard key={p.pick_id} pick={p} shadow={shadow} />
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

export function PicksTab({ ctx }: { ctx: MatchCtx }) {
  if (ctx.phase === "scheduled") return <Upcoming ctx={ctx} />;
  return (
    <div className="space-y-4">
      <Taken ctx={ctx} />
      {ctx.showAdmin && ctx.phase === "finished" ? <Postmortems ctx={ctx} /> : null}
    </div>
  );
}

/** On the Resumen: one line to the Picks tab, with how many there are (the cards themselves live there). */
export function PicksTeaser({ ctx }: { ctx: MatchCtx }) {
  const q = useMatchPicks(ctx);
  const board = q.data?.data;
  const id = Number(ctx.fixtureId);
  const count =
    ctx.phase === "scheduled"
      ? matchPicks(board, id).length
      : (board?.started ?? []).filter((p) => p.fixture_id === id).length;
  if (!q.isSuccess || count === 0) return null;
  const label =
    ctx.phase === "scheduled"
      ? t("match.picksTab.teaser", { count })
      : t("match.picksTab.teaserStarted", { count });
  return (
    <button
      type="button"
      onClick={() => ctx.goTo("picks")}
      data-testid="picks-teaser"
      className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl border border-border bg-card px-4 text-left transition-colors hover:bg-elevated/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
    >
      <span className="flex items-center gap-2 text-sm font-medium">
        <Target aria-hidden className="h-4 w-4 text-primary" />
        {label}
        {board?.source === "shadow_preview" ? <ShadowBadge compact /> : null}
      </span>
      <span className="text-xs font-semibold text-primary">{t("match.picksTab.teaserAction")}</span>
    </button>
  );
}
