/**
 * «Picks | Mis picks» at the top of both pages while the unified plan's bars are on (decision D-01): «Mis picks» left the
 * phone's bar, so it is one tap from Picks - and from «Más». Without the switch nothing is drawn: Mis picks is in the bar.
 */
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useNavFlags } from "@/components/layout/useNavFlags";

const TAB =
  "tap-y relative inline-flex h-10 flex-1 items-center justify-center rounded-full px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:flex-none";

export function PicksTabs({ current }: { current: "picks" | "mine" }) {
  const flags = useNavFlags();
  if (!flags.v2 || !flags.news) return null;
  return (
    <nav
      aria-label={t("picks.tabs.label")}
      data-testid="picks-tabs"
      className="flex w-full gap-1 rounded-full border border-border bg-card p-1 sm:w-auto sm:self-start"
    >
      <Link
        to="/picks"
        aria-current={current === "picks" ? "page" : undefined}
        className={cn(
          TAB,
          current === "picks"
            ? "bg-primary-soft text-primary"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        {t("picks.tabs.picks")}
      </Link>
      <Link
        to="/my-picks"
        aria-current={current === "mine" ? "page" : undefined}
        className={cn(
          TAB,
          current === "mine"
            ? "bg-primary-soft text-primary"
            : "text-muted-foreground hover:text-foreground",
        )}
      >
        {t("picks.tabs.mine")}
      </Link>
    </nav>
  );
}
