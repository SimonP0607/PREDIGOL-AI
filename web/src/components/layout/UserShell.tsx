/**
 * The product, for every signed-in account: five destinations and nothing technical (plan UX, A15, section 36) -
 * Inicio, Partidos, Picks, Mis picks and «Más». Desktop (1024 px and up): a top bar with the same five, «Más» a menu.
 * Phone and tablet: a compact top bar and a bottom tab bar of five cells whose labels are 12 px and whole at 320 px;
 * «Más» comes up from the bottom. The parlay slip (a floating button and its panel) follows the user across every page,
 * and so does the monthly survey's card when a useful moment brings it (plan UX, B6).
 */
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { BrandLogo } from "@/components/brand/Brand";
import { DataSourcesProvider } from "@/components/system/DataSources";
import { Disclaimer } from "@/components/system/Disclaimer";
import { Toaster } from "@/components/ui/sonner";
import { SlipProvider } from "@/product/records/slip";
import { SlipButton, SlipSheet } from "@/product/records/SlipSheet";
import { MembershipBanner } from "@/product/membership/MembershipBanner";
import { TourCard } from "@/product/tour/Tour";
import { FeedbackProvider } from "@/product/feedback/FeedbackProvider";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { BottomBar, TopNav } from "./Bars";
import { AccountMenu, LanguageSwitch, PreviewBanner } from "./HeaderControls";
import { MoreSheet } from "./MoreSheet";
import { UPDATES_PATH } from "./nav";
import { useMoreItems } from "./useMoreItems";
import { useUpdatesUnread } from "./useUpdatesUnread";

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
  const items = useMoreItems();
  // Novedades holds an entry this reader has not seen (plan UX, B6): a dot on «Más» and on its row
  const unread = useUpdatesUnread();
  const [more, setMore] = useState(false);
  // «Más» is mounted the first time it is opened: no page load pays for a sheet nobody asked for.
  const [moreUsed, setMoreUsed] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  // Any move closes «Más» (a row of it, a link behind it, the back button).
  useEffect(() => setMore(false), [pathname]);
  return (
    <DataSourcesProvider>
      <SlipProvider>
        <FeedbackProvider>
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
                <TopNav pathname={pathname} items={items} unread={unread ? [UPDATES_PATH] : []} />
                <div className="ml-auto flex items-center gap-2">
                  <LanguageSwitch />
                  <AccountMenu />
                </div>
              </div>
            </header>

            {/* The membership's notice (plan UX, A8): in the page's flow, never over the tab bar. */}
            <MembershipBanner />
            <main className="px-safe mx-auto w-full max-w-6xl pb-6 pt-5 lg:pb-12">{children}</main>
            {/* The optional tour (plan UX, A13), when the reader started it: one card over the page's foot. */}
            <TourCard />

            {/* The disclaimer (+18, no guarantee) on every screen; on a phone it also keeps the page's end clear of
              the tab bar and the parlay button. */}
            <footer className="px-safe mx-auto max-w-6xl pb-[calc(8rem+env(safe-area-inset-bottom))] text-center text-caption text-subtle-foreground short:pb-[calc(6rem+env(safe-area-inset-bottom))] lg:pb-8">
              <Disclaimer />
            </footer>

            <BottomBar
              pathname={pathname}
              moreUnread={unread}
              moreOpen={more}
              onMore={() => {
                setMoreUsed(true);
                setMore(true);
              }}
              moreRef={moreButton}
            />
            {moreUsed ? (
              <MoreSheet open={more} onOpenChange={setMore} returnFocus={moreButton} />
            ) : null}
            <SlipButton />
            <SlipSheet />
            <Toaster theme="dark" position="top-center" visibleToasts={phone ? 1 : 3} />
          </div>
        </FeedbackProvider>
      </SlipProvider>
    </DataSourcesProvider>
  );
}
