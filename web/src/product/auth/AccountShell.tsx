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

/** 16 px text and 44 px of height: a phone does not zoom in on a field it can focus. */
export const accountInput =
  "mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-ring";

export const accountButton =
  "flex h-11 w-full items-center justify-center gap-2 rounded-md bg-primary text-base font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60";

export function AccountShell({
  title,
  subtitle,
  children,
  testId,
}: {
  title: string;
  subtitle?: string | undefined;
  children: ReactNode;
  testId: string;
}) {
  return (
    <div
      className="pitch-glow relative flex min-h-screen flex-col bg-background"
      data-testid={testId}
    >
      <div className="flex justify-end p-4">
        <LanguageSwitch />
      </div>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-sm">
          <div className="flex flex-col items-center text-center">
            <BrandCrest size={96} />
            <h1 className="mt-4 font-display text-2xl font-bold tracking-tight">{title}</h1>
            {subtitle ? <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p> : null}
          </div>
          <div className="mt-6 space-y-4 rounded-xl border border-border bg-card/90 p-5 shadow-xl backdrop-blur">
            {children}
          </div>
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
      className={cn("rounded-md border px-3 py-2 text-sm leading-relaxed", style)}
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
