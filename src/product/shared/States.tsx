/** Cards, section headers and the honest empty / error / loading states of the product. */
import type { ReactNode } from "react";
import { Link, type LinkProps } from "@tanstack/react-router";
import { AlertTriangle, ChevronRight, Inbox } from "lucide-react";
import { cn } from "@/lib/utils";
import { t, translateOr } from "@/lib/i18n";
import { LiveApiError } from "@/lib/api/v1/client";

export function Card({
  children,
  className,
  premium = false,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string | undefined;
  premium?: boolean;
  as?: "section" | "article" | "div";
}) {
  return (
    <Tag
      className={cn(
        "rounded-xl border border-border bg-card",
        premium && "gold-ring bg-gradient-to-b from-gold-soft/40 to-card",
        className,
      )}
    >
      {children}
    </Tag>
  );
}

export function SectionHeader({
  title,
  subtitle,
  icon,
  action,
  className,
}: {
  title: string;
  subtitle?: string | undefined;
  icon?: ReactNode;
  action?: { label: string; to: NonNullable<LinkProps["to"]> } | undefined;
  className?: string | undefined;
}) {
  return (
    <div className={cn("flex items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <h2 className="flex items-center gap-2 font-display text-base font-semibold tracking-tight sm:text-lg">
          {icon}
          <span className="truncate">{title}</span>
        </h2>
        {subtitle ? <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p> : null}
      </div>
      {action ? (
        <Link
          to={action.to}
          className="-my-2 flex min-h-9 shrink-0 items-center gap-0.5 rounded-md px-2 text-xs font-medium text-primary hover:bg-primary/10"
        >
          {action.label}
          <ChevronRight aria-hidden className="h-3.5 w-3.5" />
        </Link>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  icon,
  action,
  className,
  compact = false,
}: {
  title: string;
  body?: ReactNode;
  icon?: ReactNode;
  action?: ReactNode;
  className?: string | undefined;
  compact?: boolean;
}) {
  return (
    <div
      data-empty-state
      className={cn(
        "flex flex-col items-center justify-center text-center",
        compact ? "gap-1.5 px-4 py-6" : "gap-2 px-6 py-10",
        className,
      )}
    >
      <div className="text-subtle-foreground">
        {icon ?? <Inbox aria-hidden className="h-6 w-6" />}
      </div>
      <p className="font-display text-sm font-semibold text-foreground">{title}</p>
      {body ? <div className="max-w-md text-xs text-muted-foreground">{body}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** An error in the reader's language: the API's code when it gave one. */
export function errorMessage(error: unknown): string {
  if (error instanceof LiveApiError) {
    if (error.status === 0) return t("errors.unreachable");
    return translateOr(`errors.code.${error.code}`, t("errors.loadFailed"));
  }
  return t("errors.loadFailed");
}

export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: unknown;
  onRetry?: (() => void) | undefined;
  className?: string | undefined;
}) {
  const rid = error instanceof LiveApiError ? error.requestId : null;
  return (
    <div
      role="alert"
      className={cn("flex flex-col items-center gap-2 px-6 py-8 text-center", className)}
    >
      <AlertTriangle aria-hidden className="h-5 w-5 text-warning" />
      <p className="text-sm font-medium">{errorMessage(error)}</p>
      {rid ? (
        <p className="numeric text-caption text-subtle-foreground">
          {t("errors.requestId", { id: rid })}
        </p>
      ) : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 rounded-md border border-border-strong px-3 py-1.5 text-xs font-medium hover:bg-elevated"
        >
          {t("common.retry")}
        </button>
      ) : null}
    </div>
  );
}

export function SkeletonBlock({ className }: { className?: string | undefined }) {
  return <div aria-hidden className={cn("animate-pulse rounded-lg bg-muted/70", className)} />;
}

export function SkeletonCards({
  count = 3,
  className,
}: {
  count?: number;
  className?: string | undefined;
}) {
  return (
    <div className={cn("grid gap-3", className)} aria-busy="true" aria-label={t("common.loading")}>
      {Array.from({ length: count }, (_, i) => (
        <SkeletonBlock key={i} className="h-24" />
      ))}
    </div>
  );
}

/** Page title for the product: big, simple, no breadcrumb noise. */
export function PageTitle({
  title,
  subtitle,
  right,
  className,
}: {
  title: string;
  subtitle?: string | undefined;
  right?: ReactNode;
  className?: string | undefined;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        <h1 className="font-display text-2xl font-bold tracking-tight sm:text-[1.75rem]">
          {title}
        </h1>
        {subtitle ? <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p> : null}
      </div>
      {right ? <div className="flex flex-wrap items-center gap-2">{right}</div> : null}
    </div>
  );
}
