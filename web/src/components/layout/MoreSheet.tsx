/**
 * «Más» (plan UX, A15, section 36): what does not fit in the five cells of the bar, one tap from any screen - Parlays,
 * Cuotas, Transparencia (once it is open to readers), Ayuda, Perfil, Glosario and Novedades, then «Instalar PrediGol» with the
 * basic steps for this device (section 35; the guided install with Android's own prompt is B7's) and «Cerrar sesión»,
 * which revokes the session on the server as the account menu does. Novedades (B6) carries a dot while it holds an
 * entry the reader has not seen.
 *
 * On a phone and a tablet it is a sheet that comes up from the bottom, under the thumb; at a desk (the top bar from
 * 1024 px) it is a menu under «Más». The list itself (MoreList) takes everything it shows as props, so it renders
 * without a session or a router's state.
 */
import { useRef, useState, type RefObject } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import { ChevronDown, ChevronRight, LogOut, Smartphone } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { installOrder, installPlatform, isStandalone, type InstallPlatform } from "@/lib/pwa";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { currentMore, UPDATES_PATH, type MoreItem } from "./nav";
import { useMoreItems } from "./useMoreItems";
import { useUpdatesUnread } from "./useUpdatesUnread";

/** «Instalar PrediGol»: the basic steps, this device's first (an iPhone has no install prompt of its own). */
export function InstallSteps({
  platform,
  defaultOpen = false,
}: {
  platform: InstallPlatform;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-lg border border-border" data-testid="more-install">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="more-install-steps"
        onClick={() => setOpen((o) => !o)}
        data-testid="more-install-toggle"
        className="flex min-h-14 w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Smartphone aria-hidden className="h-5 w-5 shrink-0 text-primary" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{t("nav.install.label")}</span>
          <span className="block text-caption text-muted-foreground">{t("nav.install.hint")}</span>
        </span>
        <ChevronDown
          aria-hidden
          className={cn(
            "h-4 w-4 shrink-0 text-subtle-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>
      {open ? (
        <div
          id="more-install-steps"
          className="space-y-2 border-t border-border px-3 py-3 text-sm"
          data-testid="more-install-steps"
        >
          {installOrder(platform).map((p, i) => (
            <p
              key={p}
              data-platform={p}
              className={i === 0 ? "text-foreground" : "text-muted-foreground"}
            >
              {t(`nav.install.${p}`)}
            </p>
          ))}
          <p className="text-caption text-muted-foreground">{t("nav.install.after")}</p>
        </div>
      ) : null}
    </div>
  );
}

/** Something not seen yet: a gold dot, and the words for a screen reader. */
export function UnreadDot({ label = "nav.unread" }: { label?: string }) {
  return (
    <>
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full bg-gold"
        data-testid="unread-dot"
      />
      <span className="sr-only">{t(label)}</span>
    </>
  );
}

/** The rows of «Más», then the install steps (not inside the installed app) and «Cerrar sesión». */
export function MoreList({
  items,
  pathname,
  standalone,
  platform,
  onPick,
  onSignOut,
  unread = [],
}: {
  items: readonly MoreItem[];
  pathname: string;
  /** Already the installed app: nothing to install. */
  standalone: boolean;
  platform: InstallPlatform;
  onPick: () => void;
  onSignOut: () => void;
  /** The rows with something the reader has not seen yet (Novedades, B6): a dot. */
  unread?: readonly string[] | undefined;
}) {
  const current = currentMore(pathname, items);
  return (
    <>
      <nav aria-label={t("nav.moreTitle")} className="mt-3">
        <ul className="grid gap-1 sm:grid-cols-2">
          {items.map((item) => {
            const Icon = item.icon;
            const here = current?.to === item.to;
            return (
              <li key={item.to}>
                <Link
                  to={item.to}
                  onClick={onPick}
                  aria-current={here ? "page" : undefined}
                  data-testid={item.testId}
                  className={cn(
                    "flex min-h-14 items-center gap-3 rounded-lg px-3 py-2 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    here && "bg-elevated",
                  )}
                >
                  <Icon
                    aria-hidden
                    className={cn("h-5 w-5 shrink-0", here ? "text-gold" : "text-muted-foreground")}
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2 text-sm font-medium">
                      {t(item.label)}
                      {unread.includes(item.to) ? <UnreadDot /> : null}
                    </span>
                    <span className="block text-caption text-muted-foreground">{t(item.hint)}</span>
                  </span>
                  <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="mt-3 space-y-2 border-t border-border pt-3">
        {standalone ? null : <InstallSteps platform={platform} />}
        <button
          type="button"
          data-testid="more-sign-out"
          onClick={onSignOut}
          className="flex min-h-12 w-full items-center gap-3 rounded-lg px-3 text-left text-sm font-medium text-negative hover:bg-negative/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <LogOut aria-hidden className="h-5 w-5 shrink-0" />
          {t("nav.signOut")}
        </button>
      </div>
    </>
  );
}

export function MoreSheet({
  open,
  onOpenChange,
  returnFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** «Más» in the bar: the focus comes back to it when the sheet closes (it is not the dialog's own trigger). */
  returnFocus?: RefObject<HTMLElement | null> | undefined;
}) {
  const auth = useAuth();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const items = useMoreItems();
  const unread = useUpdatesUnread();
  // closed by one of its rows: the reader went on to that page, so the focus does not jump back to the bar
  const picked = useRef(false);
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="bottom"
        closeLabel={t("common.close")}
        data-testid="more-sheet"
        onCloseAutoFocus={(event) => {
          if (picked.current) {
            picked.current = false;
            return;
          }
          if (!returnFocus?.current?.isConnected) return;
          event.preventDefault();
          returnFocus.current.focus();
        }}
        className="mx-auto max-h-[88dvh] max-w-2xl overflow-y-auto rounded-t-2xl pb-[calc(1rem+env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] pt-4"
      >
        <SheetHeader className="px-2 pr-12 text-left">
          <SheetTitle className="font-display text-base">{t("nav.moreTitle")}</SheetTitle>
          <SheetDescription className="sr-only">{t("nav.moreDescription")}</SheetDescription>
        </SheetHeader>
        <MoreList
          items={items}
          pathname={pathname}
          standalone={isStandalone()}
          platform={installPlatform()}
          unread={unread ? [UPDATES_PATH] : []}
          onPick={() => {
            picked.current = true;
            onOpenChange(false);
          }}
          onSignOut={() => {
            onOpenChange(false);
            void auth.signOut().then(() => navigate({ to: "/login" }));
          }}
        />
      </SheetContent>
    </Sheet>
  );
}

/** «Más» in the desk's top bar: the same items as the sheet, in a menu (the account menu keeps «Cerrar sesión»). */
export function MoreMenu({
  items,
  pathname,
  active,
  unread = [],
}: {
  items: readonly MoreItem[];
  pathname: string;
  active: boolean;
  /** The rows with something the reader has not seen yet (Novedades, B6): a dot on them and on «Más». */
  unread?: readonly string[] | undefined;
}) {
  const current = currentMore(pathname, items);
  const marked = items.some((item) => unread.includes(item.to));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid="nav-more"
        className={cn(
          "tap-y relative flex items-center gap-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          active ? "text-foreground" : "text-muted-foreground hover:text-foreground",
        )}
      >
        {t("nav.more")}
        {marked ? <UnreadDot label="nav.moreUnread" /> : null}
        <ChevronDown aria-hidden className="h-3.5 w-3.5" />
        {active ? (
          <span
            aria-hidden
            className="absolute inset-x-3 -bottom-[11px] h-0.5 rounded-full bg-gold"
          />
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72" data-testid="nav-more-menu">
        {items.map((item) => {
          const Icon = item.icon;
          const here = current?.to === item.to;
          return (
            <DropdownMenuItem key={item.to} asChild>
              <Link
                to={item.to}
                aria-current={here ? "page" : undefined}
                data-testid={`nav-${item.testId}`}
                className={cn(
                  "flex items-start gap-2.5 py-2 pointer-coarse:min-h-11",
                  here && "bg-accent",
                )}
              >
                <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0">
                  <span className="flex items-center gap-2 font-medium">
                    {t(item.label)}
                    {unread.includes(item.to) ? <UnreadDot /> : null}
                  </span>
                  <span className="block text-caption text-muted-foreground">{t(item.hint)}</span>
                </span>
              </Link>
            </DropdownMenuItem>
          );
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
