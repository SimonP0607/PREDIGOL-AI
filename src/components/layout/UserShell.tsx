/**
 * The product, for every signed-in account: six destinations and nothing technical.
 * Desktop: a top bar. Phone: a compact top bar and a bottom tab bar.
 */
import type { ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { BrandLogo } from "@/components/brand/Brand";
import { DataSourcesProvider } from "@/components/system/DataSources";
import { isActive, userNav } from "./nav";
import { AccountMenu, LanguageSwitch, PreviewBanner } from "./HeaderControls";

function ShadowPreviewStrip() {
  const auth = useAuth();
  if (!auth.shadowPreview) return null;
  return (
    <div
      data-testid="shadow-strip"
      className="flex items-center justify-center gap-2 border-b border-info/30 bg-info-soft px-4 py-1.5 text-center text-xs font-medium text-info"
    >
      <FlaskConical aria-hidden className="h-3.5 w-3.5" />
      {t("common.source.shadowPreview")}
      <button
        type="button"
        onClick={() => auth.setShadowPreview(false)}
        className="rounded border border-info/40 px-1.5 py-0.5 hover:bg-info/10"
      >
        {t("common.close")}
      </button>
    </div>
  );
}

export function UserShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  return (
    <DataSourcesProvider>
      <div className="min-h-screen bg-background">
        <PreviewBanner />
        <ShadowPreviewStrip />
        <header className="sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-6xl items-center gap-4 px-4">
            <Link to="/home" aria-label="PrediGol" className="shrink-0">
              <BrandLogo size={30} tagline={t("common.tagline")} />
            </Link>
            <nav
              aria-label={t("nav.mainNavigation")}
              className="hidden flex-1 items-center gap-1 lg:flex"
            >
              {userNav.map((item) => {
                const active = isActive(pathname, item.to, item.exact);
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    data-testid={`nav-${item.to.slice(1)}`}
                    className={cn(
                      "relative rounded-md px-3 py-1.5 text-sm font-medium transition-colors",
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
            </nav>
            <div className="ml-auto flex items-center gap-2">
              <LanguageSwitch />
              <AccountMenu />
            </div>
          </div>
        </header>

        <main className="mx-auto w-full max-w-6xl px-4 pb-28 pt-5 lg:pb-12">{children}</main>

        <footer className="mx-auto hidden max-w-6xl px-4 pb-8 text-center text-caption text-subtle-foreground lg:block">
          {t("common.disclaimer")}
        </footer>

        <nav
          aria-label={t("nav.mainNavigation")}
          className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 backdrop-blur lg:hidden"
        >
          <ul className="mx-auto grid max-w-md grid-cols-6">
            {userNav.map((item) => {
              const active = isActive(pathname, item.to, item.exact);
              const Icon = item.icon;
              return (
                <li key={item.to}>
                  <Link
                    to={item.to}
                    data-testid={`tab-${item.to.slice(1)}`}
                    className={cn(
                      "flex flex-col items-center gap-0.5 px-1 py-2 text-[0.625rem] font-medium",
                      active ? "text-gold" : "text-muted-foreground",
                    )}
                  >
                    <Icon aria-hidden className="h-5 w-5" />
                    <span className="max-w-full truncate">{t(item.label)}</span>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>
      </div>
    </DataSourcesProvider>
  );
}
