/** Language switch, account menu and the Preview-as-USER banner - shared by both shells. */
import { Link, useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff, LayoutDashboard, LogOut, UserRound } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { LOCALES, t, useI18n, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export function LanguageSwitch({ className }: { className?: string | undefined }) {
  const auth = useAuth();
  const { locale } = useI18n();
  return (
    <div
      role="group"
      aria-label={t("common.language")}
      className={cn("flex items-center rounded-md border border-border bg-card p-0.5", className)}
    >
      {LOCALES.map((l: Locale) => (
        <button
          key={l}
          type="button"
          aria-pressed={locale === l}
          data-testid={`lang-${l}`}
          onClick={() => void auth.setLocale(l)}
          className={cn(
            // Touch: wider and taller to the eye, and 44 px tall to the finger (tap-y: the two sit side by side).
            "tap-y relative rounded px-1.5 py-0.5 text-[0.7rem] font-bold uppercase tracking-wider transition-colors pointer-coarse:min-w-11 pointer-coarse:px-2 pointer-coarse:py-1.5",
            locale === l
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {l}
        </button>
      ))}
    </div>
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

export function AccountMenu() {
  const auth = useAuth();
  const navigate = useNavigate();
  const user = auth.user;
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t("common.account")}
        data-testid="account-menu"
        className="tap relative flex h-8 w-8 items-center justify-center rounded-full border border-border-strong bg-elevated text-xs font-bold text-foreground hover:border-gold/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:h-10 pointer-coarse:w-10"
      >
        {initialsOf(user.display_name)}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-64">
        <DropdownMenuLabel className="space-y-0.5">
          <div className="truncate text-sm font-semibold">{user.display_name}</div>
          <div className="truncate text-caption font-normal text-muted-foreground">
            {user.email}
          </div>
          <div className="text-[0.65rem] font-bold uppercase tracking-wider text-gold">
            {user.role}
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link to="/profile" className="flex items-center gap-2">
            <UserRound aria-hidden className="h-4 w-4" />
            {t("nav.profile")}
          </Link>
        </DropdownMenuItem>
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
