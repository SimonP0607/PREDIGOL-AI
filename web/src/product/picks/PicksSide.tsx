/**
 * The side column of Picks at a desk (plan maestro UX/UI 2026, sheet K08): the parlay of the day PrediGol built with the
 * day's picks - the same card Inicio shows - or, when there is none, the honest line and the way to Parlays. Under
 * 1024 px the page is one column and the parlay is where it always was (Inicio and Parlays).
 */
import { Link } from "@tanstack/react-router";
import type { UseQueryResult } from "@tanstack/react-query";
import { ChevronRight, Layers } from "lucide-react";
import { t } from "@/lib/i18n";
import type { Envelope } from "@/lib/api/v1/types";
import type { DailyBoard } from "@/lib/api/v1/types_records";
import { PARLAY_ICON, parlayTitle } from "@/product/parlays/parlayText";
import { ParlayRecordCard } from "@/product/records/ParlayRecordCard";
import { SectionHeader, SkeletonBlock } from "@/product/shared/States";

export function PicksSide({ board }: { board: UseQueryResult<Envelope<DailyBoard>> }) {
  const data = board.data?.data;
  const Icon = PARLAY_ICON.daily;
  const built = (data?.daily_parlay?.legs.length ?? 0) > 0;
  return (
    <aside
      className="hidden min-w-0 space-y-4 lg:block"
      data-testid="picks-side"
      aria-label={parlayTitle("daily")}
    >
      <SectionHeader
        title={parlayTitle("daily")}
        icon={<Icon aria-hidden className="h-4 w-4 shrink-0 text-gold" />}
        action={{ label: t("home.parlays.seeDetail"), to: "/parlays" }}
      />
      {!data ? (
        board.isError ? null : (
          <SkeletonBlock className="h-56 rounded-xl" />
        )
      ) : built ? (
        <ParlayRecordCard
          kind="daily"
          parlay={data.daily_parlay}
          evaluation={data.evaluation_mode}
          variant="compact"
          showTitle={false}
        />
      ) : (
        <p
          data-empty-state
          className="flex items-start gap-2.5 rounded-xl border border-border bg-card px-4 py-3 text-sm text-muted-foreground"
        >
          <Layers aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-gold" />
          <span className="min-w-0">
            {t("home.parlaysNone")}{" "}
            <Link
              to="/parlays"
              className="tap-y relative inline-flex items-center gap-0.5 whitespace-nowrap font-medium text-primary hover:underline"
            >
              {t("home.parlaysLink")}
              <ChevronRight aria-hidden className="h-3.5 w-3.5" />
            </Link>
          </span>
        </p>
      )}
    </aside>
  );
}
