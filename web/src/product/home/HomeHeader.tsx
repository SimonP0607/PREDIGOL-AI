/** Today, in the reader's zone, and how fresh what is in play is (the one freshness line of the page). */
import { Clock } from "lucide-react";
import { t } from "@/lib/i18n";
import { formatDateLong, formatRelative } from "@/lib/time";
import { GuideButton } from "@/product/guides/GuideButton";
import { SkeletonBlock } from "@/product/shared/States";
import { ShadowToggle } from "@/product/shared/ShadowToggle";

export function HomeHeader({
  freshness,
  loading,
}: {
  /** Null until the page has data: nothing is claimed about what it could not load. */
  freshness: { live_at: string | null } | null;
  loading: boolean;
}) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
      <div className="min-w-0">
        <h1 className="font-display">
          <span className="block text-label text-primary">{t("common.day.today")}</span>{" "}
          <span
            className="mt-1 block text-2xl font-bold leading-tight tracking-tight first-letter:uppercase sm:text-[1.75rem]"
            data-testid="home-date"
          >
            {formatDateLong(Date.now())}
          </span>
        </h1>
        {loading ? (
          <SkeletonBlock className="mt-2 h-3.5 w-44" />
        ) : freshness ? (
          <p
            className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground"
            data-testid="home-freshness"
          >
            <Clock aria-hidden className="h-3.5 w-3.5 shrink-0 text-subtle-foreground" />
            {freshness.live_at
              ? t("home.liveUpdated", { when: formatRelative(freshness.live_at) })
              : t("home.liveNone")}
          </p>
        ) : null}
      </div>
      {/* The «?» of Inicio (UX-070): its own guide again, at the end of the header as on every screen with a guide. */}
      <div className="flex flex-wrap items-center gap-2">
        <ShadowToggle />
        <GuideButton guide="home" />
      </div>
    </header>
  );
}
