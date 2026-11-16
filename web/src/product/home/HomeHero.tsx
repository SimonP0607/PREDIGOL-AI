/**
 * «El día en PrediGol» (plan maestro UX/UI 2026, sheets I01, I03 and I06): the day at a glance, on the pitch - how many
 * picks PrediGol recommends today, or that today there is none, and the day's facts in one line (the parlay of the day,
 * the matches of the reader's leagues, what is in play). It counts what the page already loaded: no figure of its own.
 * The owner's preview of the evaluation records says so and never calls them recommended.
 */
import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import type { DailyBoard } from "@/lib/api/v1/types_records";
import { ShadowBadge } from "@/product/shared/Bits";

export interface HeroFacts {
  /** The picks of today's set. */
  picks: number;
  /** The owner's preview: evaluation records, never a recommendation. */
  evaluation: boolean;
  /** PrediGol built today's parlay. */
  parlay: boolean;
  /** Today's matches of the reader's (or the suggested) leagues; null while not known. */
  matches: number | null;
  /** In play now; null while not known. */
  live: number | null;
}

export function heroFacts(
  board: DailyBoard | undefined,
  matches: number | null,
  live: number | null,
): HeroFacts | null {
  if (!board) return null;
  return {
    picks: board.set?.items.length ?? 0,
    evaluation: board.evaluation_mode,
    parlay: (board.daily_parlay?.legs.length ?? 0) > 0,
    matches,
    live,
  };
}

/** The day's facts, in the order they are read; one that is not known or is zero is left out. */
export function heroLine(f: HeroFacts): string[] {
  const out: string[] = [];
  if (f.parlay) out.push(t("home.hero.parlay"));
  if (f.matches) out.push(t("home.hero.matches", { count: f.matches }));
  if (f.live) out.push(t("home.hero.live", { count: f.live }));
  return out;
}

export function HomeHero({ facts, className }: { facts: HeroFacts; className?: string }) {
  const line = heroLine(facts);
  const none = facts.picks === 0;
  return (
    <section
      data-testid="home-hero"
      data-picks={facts.picks}
      aria-label={t("home.hero.overline")}
      className={cn(
        "surface-pitch relative flex flex-wrap items-center gap-x-5 gap-y-4 overflow-hidden rounded-feature px-5 py-5 sm:px-6",
        className,
      )}
    >
      {none ? null : (
        <span
          className="numeric font-display text-[3.5rem] font-bold leading-none text-primary sm:text-[4rem]"
          aria-hidden
        >
          {facts.picks}
        </span>
      )}
      <div className="min-w-0 flex-1 basis-56">
        <p className="flex flex-wrap items-center gap-2 text-overline text-primary">
          {t("home.hero.overline")}
          {facts.evaluation ? <ShadowBadge compact /> : null}
        </p>
        <p className="mt-1 font-display text-2xl font-bold leading-tight tracking-tight sm:text-[1.75rem]">
          {none ? (
            t("home.hero.none")
          ) : (
            <>
              <span className="sr-only">{facts.picks} </span>
              {t(facts.evaluation ? "home.hero.evaluation" : "home.hero.picks", {
                count: facts.picks,
              })}
            </>
          )}
        </p>
        {none ? (
          <p className="mt-1.5 text-sm text-foreground-soft">{t("home.hero.noneBody")}</p>
        ) : null}
        {line.length > 0 ? (
          <p className="mt-1.5 text-sm text-muted-foreground" data-testid="home-hero-facts">
            {line.join(" · ")}
          </p>
        ) : null}
      </div>
      <div className="flex flex-wrap gap-2">
        <Link
          to="/picks"
          data-testid="home-hero-picks"
          className={buttonVariants({ variant: none ? "secondary" : "primary" })}
        >
          {t(none ? "home.hero.why" : "home.hero.seePicks")}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
        <Link
          to="/matches"
          data-testid="home-hero-matches"
          className={cn(buttonVariants({ variant: "secondary" }), "lg:hidden")}
        >
          {t("home.hero.matchesToday")}
        </Link>
      </div>
    </section>
  );
}
