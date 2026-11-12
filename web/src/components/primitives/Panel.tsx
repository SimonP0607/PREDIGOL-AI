import { cn } from "@/lib/utils";
import { Banner } from "@/components/ui/banner";
import { EMPTY } from "@/lib/format";

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: {
  title?: string;
  subtitle?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={cn("surface-panel flex flex-col overflow-hidden", className)}>
      {title ? (
        <header className="flex items-start justify-between gap-3 border-b border-border/70 px-4 py-3.5">
          <div className="min-w-0">
            <h2 className="text-title">{title}</h2>
            {subtitle ? (
              <p className="mt-0.5 text-caption text-muted-foreground">{subtitle}</p>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn("min-w-0 flex-1", bodyClassName ?? "p-4")}>{children}</div>
    </section>
  );
}

export function MetricCard({
  label,
  value,
  hint,
  tone = "default",
  footer,
}: {
  label: string;
  value: string | null;
  hint?: string;
  tone?: "default" | "positive" | "negative" | "warning" | "muted";
  footer?: React.ReactNode;
}) {
  const toneClass = {
    default: "text-foreground",
    positive: "text-positive",
    negative: "text-negative",
    warning: "text-warning",
    muted: "text-muted-foreground",
  }[tone];
  return (
    <div className="surface-panel px-4 py-3.5">
      <div className="text-label text-subtle-foreground">{label}</div>
      {/* the system's figure (sheet 4): Archivo, 28 px, tabular */}
      <div className={cn("numeric mt-2 text-[1.75rem] font-extrabold leading-none", toneClass)}>
        {value ?? EMPTY}
      </div>
      {hint ? <div className="mt-1.5 text-caption text-muted-foreground">{hint}</div> : null}
      {footer ? <div className="mt-2">{footer}</div> : null}
    </div>
  );
}

export function KeyValue({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border/60 py-2 last:border-0">
      <span className="text-[0.8125rem] leading-snug text-muted-foreground">{label}</span>
      {/* The whole value, wrapping: cut, "0 · 16 hr ago" read "0· 16…" on a tablet, and the cut also clipped the
          finger-sized reach of a "—" that explains itself (mobile UX audit). */}
      <span className="numeric min-w-0 break-words text-right text-[0.8125rem] font-bold text-foreground">
        {value}
      </span>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-12 text-center">
      {icon ? (
        <div className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-foreground/6 text-muted-foreground">
          {icon}
        </div>
      ) : null}
      <h3 className="text-title">{title}</h3>
      <p className="max-w-md text-[0.8125rem] leading-snug text-muted-foreground">{description}</p>
      {action}
    </div>
  );
}

const BANNER_TONE = { warning: "warning", info: "info", negative: "danger" } as const;

/** The console's notice, on the system's banner (plan maestro UX/UI 2026, wave 2). */
export function WarningBanner({
  children,
  tone = "warning",
}: {
  children: React.ReactNode;
  /** negative: the fault is ours or the data contradicts itself - never shown as a mere delay. */
  tone?: keyof typeof BANNER_TONE;
}) {
  return (
    <Banner tone={BANNER_TONE[tone]} data-tone={tone} className="px-3 py-2 text-xs">
      <span className="text-foreground/85">{children}</span>
    </Banner>
  );
}
