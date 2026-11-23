/**
 * The card every advanced statistic lives in (plan EA, EA-101): a title, its line of context, the figure, and its «ficha» - what it
 * is, how it is computed, where it comes from, the sample and when it was computed - one tap away, never hidden.
 */
import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

export function ChartCard({
  title,
  subtitle,
  actions,
  method,
  footer,
  children,
  className,
  testId,
}: {
  title: string;
  subtitle?: string | undefined;
  actions?: React.ReactNode;
  /** The method in words: shown under «i». */
  method?: string | undefined;
  footer?: React.ReactNode;
  children: React.ReactNode;
  className?: string | undefined;
  testId?: string | undefined;
}) {
  return (
    <section
      className={cn("min-w-0 space-y-3 rounded-2xl border border-border bg-card p-4", className)}
      data-testid={testId}
    >
      <header className="flex flex-wrap items-start gap-2">
        <div className="min-w-0 flex-1">
          <h2 className="text-subheading">{title}</h2>
          {subtitle ? <p className="mt-0.5 text-small text-subtle-foreground">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
      </header>
      {children}
      {method ? (
        <details className="group text-small text-subtle-foreground">
          <summary className="flex min-h-11 cursor-pointer list-none items-center gap-1.5 [&::-webkit-details-marker]:hidden">
            <Info aria-hidden className="h-3.5 w-3.5" />
            <span className="underline-offset-2 group-open:underline">{title}</span>
          </summary>
          <p className="pt-1 leading-relaxed">{method}</p>
        </details>
      ) : null}
      {footer ? <div className="text-small text-subtle-foreground">{footer}</div> : null}
    </section>
  );
}

/** A small chip filter («Últimos 10 · Temporada»): one choice, 44 px tall to the touch, the system's tokens. */
export function ChipChoice<T extends string>({
  value,
  options,
  onChange,
  label,
  testId,
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (v: T) => void;
  label: string;
  testId?: string | undefined;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className="flex flex-wrap gap-1.5"
      data-testid={testId}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={on}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex min-h-11 items-center rounded-lg border px-3 text-small font-semibold transition-colors",
              on
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border bg-elevated text-foreground-soft hover:border-border-strong",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
