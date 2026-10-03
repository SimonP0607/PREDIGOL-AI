/**
 * One competition of the day: a header that stays under the app bar while its matches
 * scroll past (tap to fold it away), then its matches by kick-off.
 */
import { ChevronDown } from "lucide-react";
import { CompetitionLogo, CountryFlag } from "@/components/football/Logos";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { countryLabel } from "./country";
import { MatchRow } from "./MatchRow";
import type { CompetitionGroup } from "./model";

export function CompetitionSection({
  group,
  collapsed,
  onToggle,
}: {
  group: CompetitionGroup;
  collapsed: boolean;
  onToggle: () => void;
}) {
  const c = group.competition;
  const country = countryLabel(c.country, c.country_code);
  const headingId = `competition-${group.id}`;
  const listId = `competition-${group.id}-matches`;
  return (
    <section
      aria-labelledby={headingId}
      className="rounded-xl border border-border bg-card"
      data-testid="competition-group"
    >
      <h2
        id={headingId}
        className={cn(
          "sticky top-14 z-10 rounded-t-xl bg-card font-sans",
          collapsed ? "rounded-b-xl" : "border-b border-border/70",
        )}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          aria-controls={listId}
          className={cn(
            "flex min-h-11 w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring",
            "rounded-t-xl",
            collapsed && "rounded-b-xl",
          )}
        >
          <CompetitionLogo src={c.logo_url} name={c.name} size={18} />
          <span className="min-w-0 truncate text-sm font-semibold">{c.name}</span>
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
        <ul id={listId} className="divide-y divide-border/60 [&>li:last-child>a]:rounded-b-xl">
          {group.items.map((item) => (
            <li key={item.match.id}>
              <MatchRow item={item} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
