/**
 * The product's two navigation bars (plan UX, A15, section 36), drawn from what they are given - the page's address
 * and the items of «Más» - so they render without a session:
 *
 * - TopNav, at a desk (1024 px and up): Inicio, Partidos, Picks, Mis picks and the «Más» menu, the same groups as the
 *   phone's bar (section 37), each a pill with its icon.
 * - BottomBar, on a phone and a tablet: five cells, every label 12 px and whole at 320 px (64 px per cell; "Mis
 *   picks" needs about 50). «Más» is a button that opens its sheet. Sideways, icon and label in a row.
 *
 * «Noche de partido» (plan maestro UX/UI 2026, wave 3; the system's sheet 5): where the reader is, is a pill in the
 * action's green behind the icon - and, never by colour alone, `aria-current` and the label in the page's white.
 */
import type { ReactNode, Ref } from "react";
import { Link } from "@tanstack/react-router";
import { MoreHorizontal } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { Locale } from "@/lib/i18n";
import { MoreMenu } from "./MoreSheet";
import { destinationOf, holds, NAV_PILL, userNav, type MoreItem } from "./nav";

export function TopNav({
  pathname,
  items,
  unread,
  language,
}: {
  pathname: string;
  items: readonly MoreItem[];
  /** The rows of «Más» with something not seen yet (Novedades, B6). */
  unread?: readonly string[] | undefined;
  /** The language, chosen in «Más» since it left the bar (plan maestro UX/UI 2026, wave 3). */
  language?: { locale: Locale; onChange: (next: Locale) => void } | undefined;
}) {
  return (
    <nav aria-label={t("nav.mainNavigation")} className="hidden flex-1 items-center gap-1 lg:flex">
      {userNav.map((item) => {
        const active = holds(item, pathname);
        const Icon = item.icon;
        return (
          <Link
            key={item.to}
            to={item.to}
            data-testid={`nav-${item.to.slice(1)}`}
            data-guide={`nav-${item.to.slice(1)}`}
            aria-current={active ? "page" : undefined}
            className={cn(
              NAV_PILL,
              active
                ? "bg-primary-soft text-primary"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon aria-hidden className="h-[1.125rem] w-[1.125rem] shrink-0" />
            {t(item.label)}
          </Link>
        );
      })}
      <MoreMenu
        items={items}
        pathname={pathname}
        active={destinationOf(pathname) === "more"}
        unread={unread}
        language={language}
      />
    </nav>
  );
}

/** A cell of the bottom bar: 54 px tall (44 sideways), its label 12 px - never under the plan's minimum. */
const CELL =
  "group relative flex min-h-[3.375rem] flex-col items-center justify-center gap-1 px-0.5 pb-1 pt-1.5 text-xs font-semibold leading-tight focus-visible:outline-none short:min-h-11 short:flex-row short:gap-1.5 short:py-1";

/** The icon's pill: green behind the icon where the reader is; the keyboard's focus is drawn on it. */
function IconPill({ active, children }: { active: boolean; children: ReactNode }) {
  return (
    <span
      className={cn(
        "motion-press relative flex h-[1.875rem] w-14 shrink-0 items-center justify-center rounded-full group-focus-visible:outline-2 group-focus-visible:outline-offset-1 group-focus-visible:outline-primary short:h-7 short:w-9",
        active && "bg-primary-soft text-primary",
      )}
    >
      {children}
    </span>
  );
}

export function BottomBar({
  pathname,
  moreOpen,
  onMore,
  moreRef,
  moreUnread = false,
}: {
  pathname: string;
  moreOpen: boolean;
  onMore: () => void;
  /** «Más»: where the sheet gives the focus back when it closes. */
  moreRef?: Ref<HTMLButtonElement> | undefined;
  /** «Más» holds something the reader has not seen yet (Novedades, B6): a dot on its icon. */
  moreUnread?: boolean;
}) {
  const inMore = destinationOf(pathname) === "more";
  return (
    <nav
      aria-label={t("nav.mainNavigation")}
      className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-foreground/[0.07] bg-background-deep/90 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] backdrop-blur-lg lg:hidden"
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
                data-guide={`nav-${item.to.slice(1)}`}
                aria-current={active ? "page" : undefined}
                className={cn(CELL, active ? "text-foreground" : "text-muted-foreground")}
              >
                <IconPill active={active}>
                  <Icon aria-hidden className="h-5 w-5 shrink-0 short:h-4 short:w-4" />
                </IconPill>
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
            data-guide="nav-more"
            data-active={inMore || moreOpen ? "" : undefined}
            className={cn(
              CELL,
              "w-full cursor-pointer",
              inMore || moreOpen ? "text-foreground" : "text-muted-foreground",
            )}
          >
            <IconPill active={inMore || moreOpen}>
              <MoreHorizontal aria-hidden className="h-5 w-5 short:h-4 short:w-4" />
              {moreUnread ? (
                <span
                  aria-hidden
                  data-testid="tab-more-dot"
                  className="absolute right-3 top-[3px] h-2 w-2 rounded-full bg-gold ring-2 ring-background short:right-1 short:top-0"
                />
              ) : null}
            </IconPill>
            <span className="max-w-full truncate" data-testid="tab-label">
              {t("nav.more")}
            </span>
            {moreUnread ? <span className="sr-only">{t("nav.moreUnread")}</span> : null}
          </button>
        </li>
      </ul>
    </nav>
  );
}
