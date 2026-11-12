/**
 * One competition of the day: a header that stays under the app bar and the list's bar of days
 * and states while its matches scroll past (tap to fold it away; the fold is kept for the tab),
 * then its matches by kick-off. A league the reader follows says so on its header («Tu liga» /
 * «Sugerida»), and a match shown because of a team they follow says so on its row (plan UX, B2).
 */
import { ChevronDown } from "lucide-react";
import { CompetitionLogo, CountryFlag } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { WhyChip } from "@/product/favorites/WhyChip";
import type { Why } from "@/product/home/why";
import { countryLabel } from "./country";
import { MatchRow } from "./MatchRow";
import type { CompetitionGroup, MatchItem } from "./model";

export function CompetitionSection({
  group,
  collapsed,
  onToggle,
  why = null,
  rowWhy,
}: {
  group: CompetitionGroup;
  collapsed: boolean;
  onToggle: () => void;
  /** Why the whole competition is the reader's: a league they follow. */
  why?: Why | null;
  /** Why one of its matches is the reader's when the competition is not: a team they follow plays it. */
  rowWhy?: ((item: MatchItem) => Why | null) | undefined;
}) {
  const c = group.competition;
  const country = countryLabel(c.country, c.country_code);
  const headingId = `competition-${group.id}`;
  const listId = `competition-${group.id}-matches`;
  return (
    <section aria-labelledby={headingId} className="card-surface" data-testid="competition-group">
      <h2
        id={headingId}
        className={cn(
          // Under the app bar and under the list's own sticky bar of days and states (its height: --matches-bar-h).
          "sticky top-[calc(var(--app-sticky-top)+var(--matches-bar-h,0px))] z-10 rounded-t-card bg-card font-sans",
          collapsed ? "rounded-b-card" : "border-b border-border/70",
        )}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-controls={listId}
          className={cn(
            "flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
            "rounded-t-card",
            collapsed && "rounded-b-card",
          )}
        >
          <CompetitionLogo src={c.logo_url} name={c.name} size={18} />
          <span className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
            <span className="min-w-0 break-words font-display text-[0.8125rem] font-bold leading-tight text-foreground-soft">
              {c.name}
            </span>
            {why ? <WhyChip why={why} testId="competition-why" className="text-micro" /> : null}
          </span>
          {country ? (
            <span className="flex min-w-0 shrink-[4] items-center gap-1.5 text-caption text-muted-foreground">
              <CountryFlag src={c.flag_url} name={country} height={11} />
              {/* On a phone the flag alone says it; the name joins it when there is room. */}
              <span className={cn("truncate", c.flag_url && "hidden sm:inline")}>{country}</span>
            </span>
          ) : null}
          <span className="ml-auto flex shrink-0 items-center gap-2 pl-1">
            {group.live > 0 ? (
              <span className="inline-flex items-center gap-1 text-caption font-semibold text-primary">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-primary" />
                {t("matches.group.live", { count: group.live })}
              </span>
            ) : null}
            <span className="numeric text-caption text-subtle-foreground">
              <span aria-hidden>{group.items.length}</span>
              <span className="sr-only">
                {t("matches.group.count", { count: group.items.length })}
              </span>
            </span>
            <ChevronDown
              aria-hidden
              className={cn(
                "h-4 w-4 text-subtle-foreground transition-transform",
                collapsed && "-rotate-90",
              )}
            />
          </span>
        </button>
      </h2>
      {collapsed ? null : (
        <ul id={listId} className="divide-y divide-border/60 [&>li:last-child>div]:rounded-b-card">
          {group.items.map((item) => (
            <li key={item.match.id}>
              <MatchRow item={item} why={rowWhy ? rowWhy(item) : null} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
