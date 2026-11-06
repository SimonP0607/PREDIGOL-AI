/**
 * The frame of a page anyone may open without an account (plan UX, A4): the legal texts. The brand, the language and
 * a way in; no product navigation - nothing behind it is open to a visitor.
 */
import type { ReactNode } from "react";
import { BrandLogo } from "@/components/brand/Brand";
import { Disclaimer } from "@/components/system/Disclaimer";
import { t } from "@/lib/i18n";
import { AnnouncementBanner } from "@/product/announcements/AnnouncementBanner";
import { LanguageSwitch } from "./HeaderControls";

export function PublicShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <header className="safe-top sticky top-0 z-30 border-b border-border bg-background/85 backdrop-blur short:static">
        <div className="px-safe mx-auto flex h-14 max-w-6xl items-center gap-3 sm:gap-4">
          <a href="/login" aria-label="PrediGol" className="tap-y relative min-w-0">
            <BrandLogo size={30} tagline={t("common.tagline")} />
          </a>
          <div className="ml-auto flex items-center gap-2">
            <LanguageSwitch />
            <a
              href="/login"
              className="tap-y relative rounded-md border border-border-strong px-3 py-1.5 text-sm font-medium hover:bg-elevated"
              data-testid="public-sign-in"
            >
              {t("legal.page.signIn")}
            </a>
          </div>
        </div>
      </header>
      <AnnouncementBanner />
      <main className="px-safe mx-auto w-full max-w-6xl pb-6 pt-5 lg:pb-12">{children}</main>
      <footer className="px-safe mx-auto max-w-6xl pb-[calc(2rem+env(safe-area-inset-bottom))] text-center text-caption text-subtle-foreground">
        <Disclaimer />
      </footer>
    </div>
  );
}
