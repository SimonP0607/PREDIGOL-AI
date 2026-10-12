/**
 * The product, for every signed-in account: seven destinations and nothing technical.
 * Desktop: a top bar. Phone: a compact top bar and a bottom tab bar. The parlay slip
 * (a floating button and its panel) follows the user across every page.
 */
import type { ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { BrandLogo } from "@/components/brand/Brand";
import { DataSourcesProvider } from "@/components/system/DataSources";
import { Toaster } from "@/components/ui/sonner";
import { SlipProvider } from "@/product/records/slip";
import { SlipButton, SlipSheet } from "@/product/records/SlipSheet";
import { useMediaQuery } from "@/lib/useMediaQuery";
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
        className="tap relative rounded border border-info/40 px-2 py-0.5 hover:bg-info/10"
      >
        {t("common.close")}
      </button>
    </div>
  );
}

export function UserShell({ children }: { children: ReactNode }) {
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  // A phone shows one notice at a time: three stacked "added to your parlay" cover the top of the screen.
  const phone = useMediaQuery("(max-width: 639px)");
  return (
    <DataSourcesProvider>
      <SlipProvider>
        <div className="min-h-screen bg-background">
          <PreviewBanner />
          <ShadowPreviewStrip />
          {/* Sideways on a phone the bar scrolls away with the page: 56 px of a 390 px screen is too much. */}
          <header className="safe-top sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur short:static">
            <div className="px-safe mx-auto flex h-14 max-w-6xl items-center gap-3 sm:gap-4">
              {/* min-w-0: on a 320 px phone the brand gives way to the controls instead of pushing them off. */}
              <Link to="/home" aria-label="PrediGol" className="tap-y relative min-w-0">
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
              </nav>
              <div className="ml-auto flex items-center gap-2">
                <LanguageSwitch />
                <AccountMenu />
              </div>
            </div>
          </header>

          <main className="px-safe mx-auto w-full max-w-6xl pb-6 pt-5 lg:pb-12">{children}</main>

          {/* The disclaimer (+18, no guarantee) on every screen; on a phone it also keeps the page's end clear of
              the tab bar and the parlay button. */}
          <footer className="px-safe mx-auto max-w-6xl pb-[calc(8rem+env(safe-area-inset-bottom))] text-center text-caption text-subtle-foreground short:pb-[calc(6rem+env(safe-area-inset-bottom))] lg:pb-8">
            {t("common.disclaimer")}
          </footer>

          <nav
            aria-label={t("nav.mainNavigation")}
            className="safe-bottom fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background/95 pl-[env(safe-area-inset-left)] pr-[env(safe-area-inset-right)] backdrop-blur lg:hidden"
          >
            {/* Seven destinations, every label whole: no side padding in a cell (a 320 px phone has 46 px per
                destination; "Mis picks" needs 42 at 10 px), 11 px from 360 px. Sideways: icon and label in a row. */}
            <ul className="mx-auto grid max-w-lg grid-cols-7 short:max-w-3xl">
              {userNav.map((item) => {
                const active = isActive(pathname, item.to, item.exact);
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <Link
                      to={item.to}
                      data-testid={`tab-${item.to.slice(1)}`}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "relative flex min-h-12 flex-col items-center justify-center gap-0.5 px-0 py-1.5 text-[0.625rem] font-medium leading-tight min-[360px]:text-[0.6875rem] short:min-h-11 short:flex-row short:gap-1.5 short:py-1 short:text-xs",
                        active ? "text-gold" : "text-muted-foreground",
                      )}
                    >
                      {active ? (
                        <span
                          aria-hidden
                          className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-gold short:inset-x-6"
                        />
                      ) : null}
                      <Icon aria-hidden className="h-5 w-5 shrink-0 short:h-4 short:w-4" />
                      <span className="max-w-full truncate" data-testid="tab-label">
                        {t(item.label)}
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          <SlipButton />
          <SlipSheet />
          <Toaster theme="dark" position="top-center" visibleToasts={phone ? 1 : 3} />
        </div>
      </SlipProvider>
    </DataSourcesProvider>
  );
}
