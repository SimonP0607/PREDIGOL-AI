/**
 * «Más» (plan UX, A15, section 36): what does not fit in the five cells of the bar, one tap from any screen - Parlays,
 * Cuotas, Transparencia (once it is open to readers), Ayuda, Perfil, Glosario and Novedades, then «Instalar PrediGol» with the
 * basic steps for this device (section 35) - and, where the browser offered its own install prompt, a button that shows
 * it (B7) - and «Cerrar sesión»,
 * which revokes the session on the server as the account menu does. Novedades (B6) carries a dot while it holds an
 * entry the reader has not seen.
 *
 * On a phone and a tablet it is a sheet that comes up from the bottom, under the thumb; at a desk (the top bar from
 * 1024 px) it is a menu under «Más». The list itself (MoreList) takes everything it shows as props, so it renders
 * without a session or a router's state.
 */
import { useRef, useState, type ReactNode, type RefObject } from "react";
import { Link, useNavigate, useRouterState } from "@tanstack/react-router";
import {
  ChevronDown,
  ChevronRight,
  Download,
  Languages,
  LogOut,
  MessageCircle,
  MoreHorizontal,
  Smartphone,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t, type Locale } from "@/lib/i18n";
import {
  installOrder,
  installPlatform,
  isStandalone,
  promptInstall,
  type InstallPlatform,
} from "@/lib/pwa";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { WhatsappLink } from "@/product/support/WhatsappLink";
import { useInstallPrompt } from "@/product/push/useInstallPrompt";
import { accountState } from "@/product/profile/centre";
import { initialsOf, LanguageRadios, LanguageSwitch } from "./HeaderControls";
import {
  currentMore,
  moreHide,
  NAV_PILL,
  NAV_V1,
  privateItems,
  UPDATES_PATH,
  type MoreItem,
  type NavFlags,
} from "./nav";
import { useNavFlags } from "./useNavFlags";
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
  const canPrompt = useInstallPrompt();
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
          {canPrompt ? (
            <button
              type="button"
              onClick={() => void promptInstall()}
              data-testid="install-prompt"
              className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-primary/45 bg-primary/10 px-4 text-sm font-semibold text-primary transition-colors hover:bg-primary/15 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <Download aria-hidden className="h-4 w-4" />
              {t("push.install.button")}
            </button>
          ) : null}
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

/** The account at the head of «Más» (UX-251, decision C-03): the initials, the name and the state in words; it opens Perfil. Never the e-mail. */
export function AccountHeader({
  name,
  state,
  onPick,
  className,
}: {
  name: string;
  state: string;
  onPick?: () => void;
  className?: string;
}) {
  return (
    <Link
      to="/profile"
      onClick={onPick}
      data-testid="more-account"
      className={cn(
        "flex min-h-14 items-center gap-3 rounded-lg px-3 py-2 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      <span
        aria-hidden
        className="flex h-[2.375rem] w-9 shrink-0 items-center justify-center rounded-b-[1.125rem] rounded-t-[0.625rem] border border-gold/45 bg-linear-to-b from-accent to-elevated font-display text-xs font-extrabold text-gold-strong"
      >
        {initialsOf(name)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold">{name}</span>
        <span
          className="block truncate text-caption text-muted-foreground"
          data-testid="more-account-state"
        >
          {state}
        </span>
      </span>
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
    </Link>
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
  whatsapp = null,
  language,
  owner = [],
  account = null,
}: {
  items: readonly MoreItem[];
  /** The account's header (UX-251): name and state; none without a session. */
  account?: { name: string; state: string } | null;
  /** The owner's private rows (UX-152): under their own heading, never a reader's. */
  owner?: readonly MoreItem[];
  pathname: string;
  /** The language's control, since it left the top bar (plan maestro UX/UI 2026, wave 3): a row of its own. */
  language?: ReactNode;
  /** Already the installed app: nothing to install. */
  standalone: boolean;
  platform: InstallPlatform;
  onPick: () => void;
  onSignOut: () => void;
  /** The rows with something the reader has not seen yet (Novedades, B6): a dot. */
  unread?: readonly string[] | undefined;
  /** The WhatsApp number once the owner gave it (P7): a row «Escríbenos por WhatsApp» (no floating bubble, plan 4.2). */
  whatsapp?: string | null | undefined;
}) {
  const current = currentMore(pathname, items);
  return (
    <>
      {account ? (
        <AccountHeader
          name={account.name}
          state={account.state}
          onPick={onPick}
          className="mt-3 border border-border"
        />
      ) : null}
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
                    className={cn(
                      "h-5 w-5 shrink-0",
                      here ? "text-primary" : "text-muted-foreground",
                    )}
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
      {owner.length > 0 ? (
        <nav
          aria-label={t("nav.private.title")}
          className="mt-3 border-t border-border pt-3"
          data-testid="more-private"
        >
          <p className="px-3 text-caption font-semibold text-warning">{t("nav.private.title")}</p>
          <ul className="mt-1 grid gap-1 sm:grid-cols-2">
            {owner.map((item) => {
              const Icon = item.icon;
              return (
                <li key={item.to}>
                  <Link
                    to={item.to}
                    onClick={onPick}
                    data-testid={item.testId}
                    className="flex min-h-14 items-center gap-3 rounded-lg px-3 py-2 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <Icon aria-hidden className="h-5 w-5 shrink-0 text-warning" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">{t(item.label)}</span>
                      <span className="block text-caption text-muted-foreground">
                        {t(item.hint)}
                      </span>
                    </span>
                    <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      ) : null}
      <div className="mt-3 space-y-2 border-t border-border pt-3">
        <WhatsappLink
          digits={whatsapp}
          text={t("support.help.contact.whatsappText")}
          testId="more-whatsapp"
          className="flex min-h-14 items-center gap-3 rounded-lg px-3 py-2 hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <MessageCircle aria-hidden className="h-5 w-5 shrink-0 text-primary" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">{t("nav.whatsapp.label")}</span>
            <span className="block text-caption text-muted-foreground">
              {t("nav.whatsapp.hint")}
            </span>
          </span>
          <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
        </WhatsappLink>
        {standalone ? null : <InstallSteps platform={platform} />}
        {language ? (
          <div
            className="flex min-h-14 items-center justify-between gap-3 px-3"
            data-testid="more-language"
          >
            <span className="flex min-w-0 items-center gap-3 text-sm font-medium">
              <Languages aria-hidden className="h-5 w-5 shrink-0 text-muted-foreground" />
              {t("common.language")}
            </span>
            {language}
          </div>
        ) : null}
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
  const flags = useNavFlags();
  const owner = privateItems(auth.showAdmin, flags);
  const unread = useUpdatesUnread();
  const contact = useQuery({ ...live.supportContact, enabled: open });
  const account = auth.user
    ? {
        name: auth.user.display_name,
        state: accountState(auth.showAdmin, auth.user.membership ?? null),
      }
    : null;
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
        className="mx-auto max-h-[88dvh] max-w-2xl overflow-y-auto pb-[calc(1rem+env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))] pr-[max(0.75rem,env(safe-area-inset-right))] pt-4"
      >
        <SheetHeader className="px-2 pr-12 text-left">
          <SheetTitle className="font-display text-base">{t("nav.moreTitle")}</SheetTitle>
          <SheetDescription className="sr-only">{t("nav.moreDescription")}</SheetDescription>
        </SheetHeader>
        <MoreList
          items={items}
          owner={owner}
          account={account}
          pathname={pathname}
          standalone={isStandalone()}
          platform={installPlatform()}
          unread={unread ? [UPDATES_PATH] : []}
          whatsapp={contact.data?.whatsapp ?? null}
          language={<LanguageSwitch />}
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

/**
 * «Más» in the desk's top bar: the same items as the sheet, in a menu (the account menu keeps «Cerrar sesión»), and
 * the language below them since it left the bar.
 */
export function MoreMenu({
  items,
  pathname,
  active,
  inBar = false,
  unread = [],
  language,
  flags = NAV_V1,
  owner = [],
  account = null,
}: {
  items: readonly MoreItem[];
  /** The account's header (UX-251): name and state. */
  account?: { name: string; state: string } | null;
  /** The unified plan's bars: which rows the desk's pills replace. */
  flags?: NavFlags;
  /** The owner's private rows (UX-152). */
  owner?: readonly MoreItem[];
  pathname: string;
  active: boolean;
  /** The reader is on a destination that the wide desk's bar shows as its own pill: «Más» is not where they are there. */
  inBar?: boolean;
  /** The rows with something the reader has not seen yet (Novedades, B6): a dot on them and on «Más». */
  unread?: readonly string[] | undefined;
  language?: { locale: Locale; onChange: (next: Locale) => void } | undefined;
}) {
  const current = currentMore(pathname, items);
  const marked = items.some((item) => unread.includes(item.to));
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        data-testid="nav-more"
        data-guide="nav-more"
        data-active={active ? "" : undefined}
        className={cn(
          NAV_PILL,
          active ? "bg-primary-soft text-primary" : "text-muted-foreground hover:text-foreground",
          active && inBar && "xl:bg-transparent xl:text-muted-foreground xl:hover:text-foreground",
        )}
      >
        <MoreHorizontal aria-hidden className="h-[1.125rem] w-[1.125rem] shrink-0" />
        {t("nav.more")}
        {marked ? <UnreadDot label="nav.moreUnread" /> : null}
        <ChevronDown aria-hidden className="h-3.5 w-3.5" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-72" data-testid="nav-more-menu">
        {account ? (
          <>
            <DropdownMenuItem asChild>
              <AccountHeader name={account.name} state={account.state} className="min-h-12" />
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        ) : null}
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
                  // a pill of the bar from 1280 px: not twice
                  moreHide(item.to, flags),
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
        {owner.length > 0 ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel
              className="text-caption font-semibold text-warning"
              data-testid="nav-more-private"
            >
              {t("nav.private.title")}
            </DropdownMenuLabel>
            {owner.map((item) => {
              const Icon = item.icon;
              return (
                <DropdownMenuItem key={item.to} asChild>
                  <Link
                    to={item.to}
                    data-testid={`nav-${item.testId}`}
                    className="flex items-start gap-2.5 py-2 pointer-coarse:min-h-11"
                  >
                    <Icon aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
                    <span className="min-w-0">
                      <span className="block font-medium">{t(item.label)}</span>
                      <span className="block text-caption text-muted-foreground">
                        {t(item.hint)}
                      </span>
                    </span>
                  </Link>
                </DropdownMenuItem>
              );
            })}
          </>
        ) : null}
        {language ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-caption font-medium text-muted-foreground">
              {t("common.language")}
            </DropdownMenuLabel>
            <LanguageRadios {...language} />
          </>
        ) : null}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
