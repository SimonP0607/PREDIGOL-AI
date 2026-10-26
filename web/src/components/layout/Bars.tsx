/**
 * The product's two navigation bars (plan UX, A15, section 36), drawn from what they are given - the page's address
 * and the items of «Más» - so they render without a session:
 *
 * - TopNav, at a desk (1024 px and up): Inicio, Partidos, Picks, Mis picks and the «Más» menu, the same groups as the
 *   phone's bar (section 37).
 * - BottomBar, on a phone and a tablet: five cells, every label 12 px and whole at 320 px (64 px per cell; "Mis
 *   picks" needs about 50). «Más» is a button that opens its sheet. Sideways, icon and label in a row.
 */
import type { Ref } from "react";
import { Link } from "@tanstack/react-router";
import { MoreHorizontal } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { MoreMenu } from "./MoreSheet";
import { destinationOf, holds, userNav, type MoreItem } from "./nav";

export function TopNav({ pathname, items }: { pathname: string; items: readonly MoreItem[] }) {
  return (
    <nav aria-label={t("nav.mainNavigation")} className="hidden flex-1 items-center gap-1 lg:flex">
      {userNav.map((item) => {
        const active = holds(item, pathname);
        return (
          <Link
            key={item.to}
            to={item.to}
            data-testid={`nav-${item.to.slice(1)}`}
            aria-current={active ? "page" : undefined}
            className={cn(
              "tap-y relative rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
              active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(item.label)}
            {active ? (
              <span
                aria-hidden
                className="absolute inset-x-3 -bottom-[11px] h-0.5 rounded-full bg-gold"
              />
            ) : null}
          </Link>
        );
      })}
      <MoreMenu items={items} pathname={pathname} active={destinationOf(pathname) === "more"} />
    </nav>
  );
}

/** A cell of the bottom bar: 48 px tall (44 sideways), its label 12 px - never under the plan's minimum. */
const CELL =
  "relative flex min-h-12 flex-col items-center justify-center gap-0.5 px-0.5 py-1 text-xs font-medium leading-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring short:min-h-11 short:flex-row short:gap-1.5 short:py-1";

function ActiveLine() {
  return (
    <span
      aria-hidden
      className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-gold short:inset-x-6"
    />
  );
}

export function BottomBar({
  pathname,
  moreOpen,
  onMore,
  moreRef,
}: {
  pathname: string;
  moreOpen: boolean;
  onMore: () => void;
  /** «Más»: where the sheet gives the focus back when it closes. */
  moreRef?: Ref<HTMLButtonElement> | undefined;
}) {
  const inMore = destinationOf(pathname) === "more";
  return (
    <nav
      aria-label={t("nav.mainNavigation")}
      className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] backdrop-blur lg:hidden"
    >
      <ul className="mx-auto grid max-w-lg grid-cols-5 short:max-w-3xl">
        {userNav.map((item) => {
          const active = holds(item, pathname);
          const Icon = item.icon;
          return (
            <li key={item.to}>
              <Link
                to={item.to}
                data-testid={`tab-${item.to.slice(1)}`}
                aria-current={active ? "page" : undefined}
                className={cn(CELL, active ? "text-gold" : "text-muted-foreground")}
              >
                {active ? <ActiveLine /> : null}
                <Icon aria-hidden className="h-5 w-5 shrink-0 short:h-4 short:w-4" />
                <span className="max-w-full truncate" data-testid="tab-label">
                  {t(item.label)}
                </span>
              </Link>
            </li>
          );
        })}
        <li>
          <button
            ref={moreRef}
            type="button"
            onClick={onMore}
            aria-haspopup="dialog"
            aria-expanded={moreOpen}
            data-testid="tab-more"
            className={cn(
              CELL,
              "w-full",
              inMore || moreOpen ? "text-gold" : "text-muted-foreground",
            )}
          >
            {inMore ? <ActiveLine /> : null}
            <MoreHorizontal aria-hidden className="h-5 w-5 shrink-0 short:h-4 short:w-4" />
            <span className="max-w-full truncate" data-testid="tab-label">
              {t("nav.more")}
            </span>
          </button>
        </li>
      </ul>
    </nav>
  );
}
