/** Language switch, account menu and the Preview-as-USER banner - shared by both shells. */
import { Link, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  BookOpen,
  Eye,
  EyeOff,
  LayoutDashboard,
  LifeBuoy,
  LogOut,
  UserRound,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { LOCALES, t, useI18n, type Locale } from "@/lib/i18n";
import { LOCALE_NAMES } from "@/lib/i18n/catalogs";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * The language, as a segmented pair («Noche de partido», the system's sheet 3). Before the product (sign-in, the
 * account's pages, legal texts) it sits at the top; with a session it lives in «Más» and in Perfil, and in the
 * console in the account's menu (plan maestro UX/UI 2026, wave 3). Each button says its code and, to a screen reader,
 * the language's own name after it: the name a voice user says is the one on the screen (WCAG 2.5.3).
 */
export function LanguageSwitch({ className }: { className?: string | undefined }) {
  const auth = useAuth();
  const { locale } = useI18n();
  return (
    <div
      role="group"
      aria-label={t("common.language")}
      className={cn(
        "inline-flex shrink-0 items-center rounded-full border border-border bg-card p-[3px]",
        className,
      )}
    >
      {LOCALES.map((l: Locale) => (
        <button
          key={l}
          type="button"
          aria-pressed={locale === l}
          title={LOCALE_NAMES[l]}
          lang={l}
          data-testid={`lang-${l}`}
          onClick={() => void auth.setLocale(l)}
          className={cn(
            // 32 px to the eye and 44 px tall to the finger (tap-y: the two sit side by side)
            "tap-y motion-press relative inline-flex h-8 min-w-[2.375rem] cursor-pointer items-center justify-center rounded-full px-2.5 font-display text-xs font-bold uppercase tracking-[0.04em] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary pointer-coarse:min-w-11",
            locale === l
              ? "bg-primary-soft text-primary"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {l}
          <span className="sr-only">{LOCALE_NAMES[l]}</span>
        </button>
      ))}
    </div>
  );
}

/** The language inside a menu: one radio item per language, its own name in its own language. */
export function LanguageRadios({
  locale,
  onChange,
}: {
  locale: Locale;
  onChange: (next: Locale) => void;
}) {
  return (
    <DropdownMenuRadioGroup value={locale} onValueChange={(next) => onChange(next as Locale)}>
      {LOCALES.map((l: Locale) => (
        <DropdownMenuRadioItem
          key={l}
          value={l}
          lang={l}
          data-testid={`lang-${l}`}
          className="pointer-coarse:min-h-11"
        >
          {LOCALE_NAMES[l]}
        </DropdownMenuRadioItem>
      ))}
    </DropdownMenuRadioGroup>
  );
}

function initialsOf(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join("") || "?"
  );
}

export function AccountMenu({
  language = false,
}: {
  /** The console's menu carries the language (the product's «Más» does, for a reader). */
  language?: boolean;
}) {
  const auth = useAuth();
  const { locale } = useI18n();
  const navigate = useNavigate();
  const user = auth.user;
  if (!user) return null;
  const initials = initialsOf(user.display_name);
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        // the initials on the screen open the name a screen reader says (WCAG 2.5.3)
        aria-label={`${initials}, ${t("common.account")}`}
        data-testid="account-menu"
        className="tap motion-press relative flex h-[2.375rem] w-9 shrink-0 cursor-pointer items-center justify-center rounded-b-[1.125rem] rounded-t-[0.625rem] border border-gold/45 bg-linear-to-b from-accent to-elevated font-display text-xs font-extrabold text-gold-strong hover:border-gold/80 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
      >
        {initials}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="space-y-0.5">
          <div className="truncate text-sm font-semibold">{user.display_name}</div>
          <div className="truncate text-caption font-normal text-muted-foreground">
            {user.email}
          </div>
          {/* Plan UX, A1 (F07): a reader never sees an internal role ("USER"); the owner sees "Administrador". */}
          {user.role === "SUPER_ADMIN" ? (
            <div
              className="text-micro font-bold uppercase tracking-wider text-gold"
              data-testid="account-role"
            >
              {t("common.roleAdmin")}
            </div>
          ) : null}
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/profile" className="flex items-center gap-2">
            <UserRound aria-hidden className="h-4 w-4" />
            {t("nav.profile")}
          </Link>
        </DropdownMenuItem>
        {/* plan UX, A14: Ayuda - the questions, the contact and the reader's messages - two taps from any screen */}
        <DropdownMenuItem asChild>
          <Link to="/help" className="flex items-center gap-2" data-testid="go-help">
            <LifeBuoy aria-hidden className="h-4 w-4" />
            {t("nav.help")}
          </Link>
        </DropdownMenuItem>
        {/* plan UX, A3: every word PrediGol uses, one definition each («Más» carries it too, A15) */}
        <DropdownMenuItem asChild>
          <Link to="/help/glossary" className="flex items-center gap-2" data-testid="go-glossary">
            <BookOpen aria-hidden className="h-4 w-4" />
            {t("nav.glossary")}
          </Link>
        </DropdownMenuItem>
        {/* plan UX, A12: «Cómo le va a PrediGol», once it is open to readers (the owner reviews it before) */}
        {user.transparency || auth.showAdmin ? (
          <DropdownMenuItem asChild>
            <Link
              to="/transparency"
              className="flex items-center gap-2"
              data-testid="go-transparency"
            >
              <BarChart3 aria-hidden className="h-4 w-4" />
              {t("transparency.page.link")}
            </Link>
          </DropdownMenuItem>
        ) : null}
        {auth.isSuperAdmin && !auth.previewAsUser ? (
          <DropdownMenuItem asChild>
            <Link to="/admin/overview" className="flex items-center gap-2" data-testid="go-admin">
              <LayoutDashboard aria-hidden className="h-4 w-4" />
              {t("nav.adminConsole")}
            </Link>
          </DropdownMenuItem>
        ) : null}
        {auth.isSuperAdmin ? (
          <DropdownMenuItem
            data-testid="toggle-preview"
            onSelect={() => {
              const next = !auth.previewAsUser;
              auth.setPreviewAsUser(next);
              if (next) void navigate({ to: "/home" });
            }}
            className="flex items-center gap-2"
          >
            {auth.previewAsUser ? (
              <EyeOff aria-hidden className="h-4 w-4" />
            ) : (
              <Eye aria-hidden className="h-4 w-4" />
            )}
            {auth.previewAsUser ? t("nav.exitPreview") : t("nav.previewAsUser")}
          </DropdownMenuItem>
        ) : null}
        {language ? (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel className="text-caption font-medium text-muted-foreground">
              {t("common.language")}
            </DropdownMenuLabel>
            <LanguageRadios locale={locale} onChange={(next) => void auth.setLocale(next)} />
          </>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          data-testid="sign-out"
          onSelect={() => {
            void auth.signOut().then(() => navigate({ to: "/login" }));
          }}
          className="flex items-center gap-2 text-negative focus:text-negative"
        >
          <LogOut aria-hidden className="h-4 w-4" />
          {t("nav.signOut")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Always visible while a SUPER_ADMIN previews the USER experience. */
export function PreviewBanner() {
  const auth = useAuth();
  const navigate = useNavigate();
  if (!auth.previewAsUser) return null;
  return (
    <div
      data-testid="preview-banner"
      className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-b border-gold/40 bg-gold-soft px-4 py-2 text-center text-xs text-gold-strong"
    >
      <Eye aria-hidden className="h-3.5 w-3.5" />
      <span className="font-semibold">{t("nav.previewing")}</span>
      <span className="hidden text-gold/80 sm:inline">· {t("nav.previewNote")}</span>
      <button
        type="button"
        data-testid="exit-preview"
        onClick={() => {
          auth.setPreviewAsUser(false);
          void navigate({ to: "/admin/overview" });
        }}
        className="tap relative rounded-md border border-gold/50 px-2 py-0.5 font-semibold hover:bg-gold/15"
      >
        {t("nav.exitPreview")}
      </button>
    </div>
  );
}
