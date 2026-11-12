/**
 * The frame of the pages that get a reader in without the owner (plan UX, A7): activating an invitation, asking for
 * a new password, choosing it, unlocking an account. The sign-in page's look, one column at 320 px, and inputs of
 * 16 px with 44 px of height, so a phone neither zooms in nor misses a tap; the fields carry the autocomplete names the
 * system's password manager needs.
 */
import type { ReactNode } from "react";
import { BrandCrest } from "@/components/brand/Brand";
import { LanguageSwitch } from "@/components/layout/HeaderControls";
import { Disclaimer } from "@/components/system/Disclaimer";
import { cn } from "@/lib/utils";
import { fieldVariants } from "@/components/ui/field";

/** 16 px text and 44 px of height: a phone does not zoom in on a field it can focus. */
export const accountInput = cn(fieldVariants(), "mt-1");

export const accountButton =
  "flex h-11 w-full items-center justify-center gap-2 rounded-md bg-primary text-base font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60";

/**
 * The language switch at the top of the pages before the product (sign-in, account pages, two-step verification).
 * Installed on an iPhone the page runs under the status bar (black-translucent, viewport-fit=cover): the bar keeps its
 * 16 px below the clock and clear of the notch held sideways, and stays exactly 16 px in a browser, where the insets
 * are 0 (mobile UX plan, UX-093).
 */
export function AccountTopBar({ children }: { children: ReactNode }) {
  return (
    <div
      className="flex justify-end pb-4 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-[calc(1rem+env(safe-area-inset-top))]"
      data-testid="account-top-bar"
    >
      {children}
    </div>
  );
}

export function AccountShell({
  title,
  subtitle,
  children,
  testId,
  sections = false,
}: {
  title: string;
  subtitle?: string | undefined;
  children: ReactNode;
  testId: string;
  /** The page draws its own cards, one per group of fields (sheet A03, «Crea tu cuenta»): no card around them. */
  sections?: boolean;
}) {
  return (
    <div
      className="pitch-glow relative flex min-h-screen flex-col bg-background"
      data-testid={testId}
    >
      <AccountTopBar>
        <LanguageSwitch />
      </AccountTopBar>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className={cn("w-full", sections ? "max-w-md" : "max-w-sm")}>
          <div className="flex flex-col items-center text-center">
            <BrandCrest size={96} />
            <h1 className="mt-4 text-display text-balance">{title}</h1>
            {subtitle ? <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p> : null}
          </div>
          {sections ? (
            <div className="mt-6 space-y-3.5">{children}</div>
          ) : (
            <div className="card-surface mt-6 space-y-4 rounded-feature p-5 shadow-xl">
              {children}
            </div>
          )}
          <Disclaimer className="mt-6 text-center text-caption text-subtle-foreground" />
        </div>
      </main>
    </div>
  );
}

export function Notice({
  tone,
  children,
  testId,
}: {
  tone: "info" | "ok" | "error" | "warning";
  children: ReactNode;
  testId?: string;
}) {
  const style = {
    info: "border-info/30 bg-info-soft text-foreground",
    ok: "border-positive/40 bg-positive-soft text-foreground",
    error: "border-negative/40 bg-negative-soft text-negative",
    warning: "border-warning/40 bg-warning-soft text-warning",
  }[tone];
  return (
    <p
      role={tone === "error" ? "alert" : "status"}
      data-testid={testId}
      // the system's banner (sheet 5): 14 px radius, a soft surface of its tone
      className={cn("rounded-control border px-3.5 py-3 text-sm leading-snug", style)}
    >
      {children}
    </p>
  );
}

/** A link styled as the secondary way out of a page (back to the sign-in, ask for a new link). */
export function SideLink({
  href,
  children,
  testId,
}: {
  href: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <a
      href={href}
      data-testid={testId}
      className="tap-y relative block text-center text-sm text-primary underline-offset-2 hover:underline"
    >
      {children}
    </a>
  );
}

/**
 * A group of fields of a long form (sheet A03): a card with its number and its name. The number is the order on the
 * page, nothing to press - the form is one page and one button.
 */
export function FormSection({
  n,
  title,
  children,
  testId,
}: {
  n: number;
  title: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <section className="card-surface space-y-3.5 rounded-feature p-4" data-testid={testId}>
      <h2 className="flex items-center gap-2.5 text-title">
        <span
          aria-hidden
          className="numeric inline-flex h-[1.625rem] w-[1.625rem] shrink-0 items-center justify-center rounded-full bg-primary-soft font-display text-[0.8125rem] font-extrabold text-primary"
        >
          {n}
        </span>
        {title}
      </h2>
      {children}
    </section>
  );
}
