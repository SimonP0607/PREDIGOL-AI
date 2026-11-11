/** Cards, section headers and the honest empty / error / loading states of the product. */
import { useEffect, type ReactNode } from "react";
import { Link, type LinkProps } from "@tanstack/react-router";
import { AlertTriangle, ChevronRight, Inbox, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { t, translateOr } from "@/lib/i18n";
import { LiveApiError } from "@/lib/api/v1/client";
import { markTrouble } from "@/lib/feedback/session";
import { track } from "@/lib/track";
import type { GuideKey } from "@/lib/api/v1/types_guides";
import { GuideButton } from "@/product/guides/GuideButton";
import { reportShownApiError } from "@/lib/observability";
import { useReportProblem } from "@/product/support/report";
import { StillFailing } from "@/product/support/StillFailing";

/**
 * The card of «Noche de partido» (plan maestro UX/UI 2026, wave 2). `premium`: the gold card of what PrediGol
 * recommends; `lift`: one step higher, for a block inside a card or over a scene.
 */
export function Card({
  children,
  className,
  premium = false,
  lift = false,
  as: Tag = "section",
  id,
  "data-testid": testId,
}: {
  children: ReactNode;
  className?: string | undefined;
  premium?: boolean;
  lift?: boolean;
  as?: "section" | "article" | "div";
  /** An anchor a link can lead to (an e-mail's button: /profile#privacy). */
  id?: string | undefined;
  /** The handle the end-to-end tests find the card by (the customer's card, the Product page). */
  "data-testid"?: string | undefined;
}) {
  return (
    <Tag
      id={id}
      data-testid={testId}
      className={cn(
        "card-surface",
        lift && "border-border-strong bg-elevated bg-none",
        premium && "surface-gold hairline-gold rounded-feature",
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
        <h2 className="flex items-center gap-2 text-heading">
          {icon}
          {/* The whole title, on two lines if need be (mobile UX plan, UX-095): cut with «…» it lost the end of
          «Todas las selecciones que cumplen la regla» on a 320 px phone. */}
          <span className="min-w-0 break-words">{title}</span>
        </h2>
        {subtitle ? <p className="mt-1 text-small text-muted-foreground">{subtitle}</p> : null}
      </div>
      {action ? (
        <Link
          to={action.to}
          className="tap-y relative -my-2 flex min-h-9 shrink-0 items-center gap-0.5 rounded-chip px-2 text-sm font-semibold text-primary hover:bg-primary-soft"
        >
          {action.label}
          <ChevronRight aria-hidden className="h-4 w-4" />
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
        compact ? "gap-1.5 px-4 py-6" : "gap-2 px-5 py-8",
        className,
      )}
    >
      <div
        className={cn(
          "flex items-center justify-center bg-foreground/[0.05] text-foreground-soft",
          compact ? "h-8 w-8 rounded-[0.625rem]" : "mb-1 h-10 w-10 rounded-field",
        )}
      >
        {icon ?? <Inbox aria-hidden className={compact ? "h-4 w-4" : "h-5 w-5"} />}
      </div>
      <p className={cn("text-foreground", compact ? "text-title" : "text-subheading")}>{title}</p>
      {body ? <div className="max-w-md text-small text-muted-foreground">{body}</div> : null}
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
  const code = error instanceof LiveApiError ? error.code : "client";
  const status = error instanceof LiveApiError ? error.status : 0;
  // Plan UX, A14: from every error, «Reportar un problema» with this error's reference (never on the owner's console).
  const report = useReportProblem();
  // Plan UX, A6: which errors readers see (the code and the status, never the message); B6: and after one, no survey.
  useEffect(() => {
    track("error_shown", { code: /^[A-Za-z0-9_.+-]{1,40}$/.test(code) ? code : "other", status });
    markTrouble();
    // the error the reader SAW, with its reference, to Sentry when it is on (closing plan 5.3; once per reference)
    if (error instanceof LiveApiError) reportShownApiError({ status, code, requestId: rid });
  }, [error, code, status, rid]);
  return (
    <div
      role="alert"
      className={cn("flex flex-col items-center gap-2 px-6 py-8 text-center", className)}
    >
      <span className="mb-1 flex h-10 w-10 items-center justify-center rounded-field bg-warning/[0.14] text-warning">
        <AlertTriangle aria-hidden className="h-5 w-5" />
      </span>
      <p className="text-subheading">{errorMessage(error)}</p>
      {rid ? (
        <p className="numeric text-caption text-subtle-foreground">
          {t("errors.requestId", { id: rid })}
        </p>
      ) : null}
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry} className="mt-1">
          <RefreshCw aria-hidden />
          {t("common.retry")}
        </Button>
      ) : null}
      {report.available ? (
        <button
          type="button"
          onClick={() => report.open({ category: "technical", requestId: rid })}
          data-testid="error-report"
          className="tap-y relative mt-0.5 rounded-sm text-xs font-medium text-primary underline-offset-4 hover:underline"
        >
          {t("support.report.title")}
        </button>
      ) : null}
      {report.available ? <StillFailing requestId={rid} /> : null}
    </div>
  );
}

/**
 * A refresh failed but the last answer is still on the page (plan Inicio, 1.4, F6): keep what was seen, say so in one small
 * line and offer to try again - an error never wipes the data that is already there.
 */
export function StaleNote({
  onRetry,
  className,
}: {
  onRetry?: (() => void) | undefined;
  className?: string | undefined;
}) {
  return (
    <p
      role="status"
      data-testid="stale-note"
      className={cn("flex flex-wrap items-center gap-x-2 text-caption text-warning", className)}
    >
      <AlertTriangle aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span>{t("errors.refreshFailed")}</span>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="tap-y relative rounded-sm font-medium underline underline-offset-4 hover:text-foreground"
        >
          {t("common.retry")}
        </button>
      ) : null}
    </p>
  );
}

export function SkeletonBlock({ className }: { className?: string | undefined }) {
  // the outline of what is coming, in the system's two greys; «reduce motion» stills it (styles.css)
  return (
    <div
      aria-hidden
      className={cn(
        "animate-pulse rounded-lg bg-linear-to-r from-elevated via-popover to-elevated",
        className,
      )}
    />
  );
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
  guide,
  className,
}: {
  title: string;
  /** Text, or text with a glossary term in it (plan UX, A3: «¿Qué es un pick?»). */
  subtitle?: ReactNode;
  right?: ReactNode;
  /** The screen's guide: its «?» goes at the end of the header (plan UX-052). */
  guide?: GuideKey;
  className?: string | undefined;
}) {
  return (
    <div className={cn("flex flex-wrap items-end justify-between gap-3", className)}>
      <div className="min-w-0">
        {/* a long title (a legal document's) on the narrowest phone: a step smaller, so it is three lines and not four */}
        <h1 className="text-balance text-display max-[359px]:text-[1.625rem]">{title}</h1>
        {subtitle ? <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p> : null}
      </div>
      {right || guide ? (
        <div className="flex flex-wrap items-center gap-2">
          {right}
          {guide ? <GuideButton guide={guide} /> : null}
        </div>
      ) : null}
    </div>
  );
}
