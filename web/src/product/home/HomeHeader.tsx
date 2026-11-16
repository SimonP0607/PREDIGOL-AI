/** Today, in the reader's zone, and how fresh what is in play is (the one freshness line of the page). */
import type { ReactNode } from "react";
import { Clock } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { formatDateLong, formatRelative } from "@/lib/time";
import { GuideButton } from "@/product/guides/GuideButton";
import { SkeletonBlock } from "@/product/shared/States";
import { ShadowToggle } from "@/product/shared/ShadowToggle";

/** A first name longer than this is not used in the greeting: the page says the day instead. */
export const GREETING_MAX = 18;

export function HomeHeader({
  freshness,
  loading,
  name,
  selector,
}: {
  /** Null until the page has data: nothing is claimed about what it could not load. */
  freshness: { live_at: string | null } | null;
  loading: boolean;
  /** How the reader is greeted (their name's first word); without it, the page's title is the day. */
  name?: string | null | undefined;
  /** «Para ti / Todo», beside the greeting at a desk and under it on a phone (sheets I02 and I06). */
  selector?: ReactNode;
}) {
  // the name's first word; a long one without spaces is an address or a handle, not how anybody is greeted
  const word = name?.trim().split(/\s+/)[0] ?? "";
  const first = word.length <= GREETING_MAX ? word : "";
  return (
    <header className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
      <div className="min-w-0">
        <h1 className="font-display">
          {/* the day above the greeting, in the reader's zone (sheet I01) */}
          <span className="block text-label text-primary">
            <span className="sr-only">{t("common.day.today")} </span>
            <span className="first-letter:uppercase" data-testid="home-date">
              {formatDateLong(Date.now())}
            </span>
          </span>{" "}
          <span
            className="mt-1 block text-2xl font-bold leading-tight tracking-tight [overflow-wrap:anywhere] sm:text-[1.75rem]"
            data-testid="home-hello"
          >
            {first ? t("home.hello", { name: first }) : t("common.day.today")}
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
      <div
        className={cn(
          "flex flex-wrap items-center gap-2",
          // with the selector the group takes its own line on a phone, the selector across it
          selector ? "max-sm:w-full max-sm:justify-end" : "",
        )}
      >
        {selector}
        <ShadowToggle />
        <GuideButton guide="home" />
      </div>
    </header>
  );
}
