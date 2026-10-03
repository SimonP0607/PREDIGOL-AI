/**
 * The day's top value picks. Phones swipe through them (the next card peeks in, so the
 * rest of Home stays close); tablets and desktops see them as a grid.
 */
import { Link } from "@tanstack/react-router";
import { ArrowRight, ChevronRight, Target } from "lucide-react";
import { t } from "@/lib/i18n";
import type { Section } from "@/lib/api/v1/types";
import type { PickCard as PickCardData } from "@/lib/api/v1/types_product";
import { PickCard } from "@/product/shared/PickCard";
import { Card, EmptyState, SectionHeader } from "@/product/shared/States";
import { emptyReason } from "@/product/shared/markets";

// `text-caption` on the item: the shared card's competition tag and price age inherit
// their size from here, because cn() (tailwind-merge) drops their own `text-caption`
// when a text colour follows it. Harmless once cn() knows the custom sizes.
const ITEM = "w-[88%] max-w-[23rem] shrink-0 snap-start text-caption md:w-auto md:max-w-none";

export function TopPicks({
  section,
  shadow,
}: {
  section: Section<PickCardData[]>;
  shadow: boolean;
}) {
  const picks = section.data.slice(0, 5);
  return (
    <section data-testid="home-top-picks">
      <SectionHeader
        title={t("home.picks.title")}
        icon={<Target aria-hidden className="h-4 w-4 shrink-0 text-primary" />}
        action={{ label: t("home.picks.seeAll"), to: "/picks" }}
      />
      {picks.length === 0 ? (
        <Card className="mt-3">
          <EmptyState
            icon={<Target aria-hidden className="h-6 w-6" />}
            title={emptyReason(section.reason) || t("home.picks.empty")}
            body={t("home.picks.emptyBody")}
            action={
              <Link
                to="/picks"
                className="inline-flex min-h-9 items-center gap-1 rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-elevated"
              >
                {t("home.picks.emptyCta")}
                <ChevronRight aria-hidden className="h-3.5 w-3.5" />
              </Link>
            }
          />
        </Card>
      ) : (
        <ul
          aria-label={t("home.picks.list")}
          className="-mx-4 mt-3 flex snap-x snap-mandatory scroll-px-4 gap-3 overflow-x-auto px-4 pb-1 [scrollbar-width:none] md:mx-0 md:grid md:grid-cols-2 md:gap-4 md:overflow-visible md:px-0 md:pb-0 xl:grid-cols-3 [&::-webkit-scrollbar]:hidden"
        >
          {picks.map((pick, i) => (
            <li key={pick.pick_id} className={ITEM}>
              <PickCard pick={pick} rank={i + 1} shadow={shadow} className="h-full" />
            </li>
          ))}
          <li className="w-40 shrink-0 snap-start md:w-auto">
            <Link
              to="/picks"
              className="flex h-full min-h-[9rem] flex-col items-center justify-center gap-2.5 rounded-xl border border-dashed border-border-strong p-5 text-center text-sm font-medium text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-elevated text-primary">
                <ArrowRight aria-hidden className="h-5 w-5" />
              </span>
              {t("home.picks.allTile")}
            </Link>
          </li>
        </ul>
      )}
    </section>
  );
}
