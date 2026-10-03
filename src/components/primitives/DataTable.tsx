import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";

export function TableShell({
  children,
  className,
  compact = false,
}: {
  children: React.ReactNode;
  className?: string;
  /** Drop the 36rem minimum width: for narrow tables that fit a side column. */
  compact?: boolean;
}) {
  return (
    <div className={cn("w-full overflow-x-auto", className)}>
      <table
        className={cn("w-full border-collapse text-sm", compact ? "min-w-0" : "min-w-[36rem]")}
      >
        {children}
      </table>
    </div>
  );
}

export function THead({ children }: { children: React.ReactNode }) {
  return (
    <thead className="sticky top-0 z-10 bg-card">
      <tr className="border-b border-border">{children}</tr>
    </thead>
  );
}

export function TH({
  children,
  align = "left",
  className,
  title,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
  title?: string;
}) {
  return (
    <th
      scope="col"
      title={title}
      className={cn(
        "px-3 py-2 text-label font-semibold text-subtle-foreground whitespace-nowrap",
        align === "right" && "text-right",
        align === "center" && "text-center",
        align === "left" && "text-left",
        className,
      )}
    >
      {children}
    </th>
  );
}

export function TRow({
  children,
  onClick,
  selected,
  className,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  selected?: boolean;
  className?: string;
}) {
  return (
    <tr
      onClick={onClick}
      tabIndex={onClick ? 0 : undefined}
      onKeyDown={
        onClick
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onClick();
              }
            }
          : undefined
      }
      className={cn(
        "border-b border-border/60 transition-colors last:border-0",
        onClick &&
          "cursor-pointer hover:bg-elevated/70 focus:bg-elevated focus:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        selected && "bg-primary/8 hover:bg-primary/10",
        className,
      )}
    >
      {children}
    </tr>
  );
}

export function TD({
  children,
  align = "left",
  className,
}: {
  children: React.ReactNode;
  align?: "left" | "right" | "center";
  className?: string;
}) {
  return (
    <td
      className={cn(
        "px-3 py-2.5 align-middle",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      {children}
    </td>
  );
}

export function TableSkeleton({ rows = 6, cols = 6 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2 p-4" role="status" aria-busy="true" aria-label={t("common.loading")}>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <div
              key={c}
              className="h-4 flex-1 animate-pulse rounded bg-muted"
              style={{ animationDelay: `${(r * cols + c) * 20}ms` }}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

/** Sortable column header. Announces sort state via aria-sort. */
export function SortableTH({
  children,
  active,
  direction,
  onClick,
  align = "left",
  className,
  title,
}: {
  children: React.ReactNode;
  active: boolean;
  direction: "asc" | "desc";
  onClick: () => void;
  align?: "left" | "right" | "center";
  className?: string;
  title?: string;
}) {
  return (
    <th
      scope="col"
      title={title}
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
      className={cn(
        "px-3 py-2 text-label font-semibold text-subtle-foreground whitespace-nowrap",
        align === "right" && "text-right",
        align === "center" && "text-center",
        className,
      )}
    >
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "inline-flex items-center gap-1 rounded transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          active && "text-foreground",
          align === "right" && "flex-row-reverse",
        )}
      >
        {children}
        <span aria-hidden className="text-[0.65em] opacity-70">
          {active ? (direction === "asc" ? "▲" : "▼") : "↕"}
        </span>
      </button>
    </th>
  );
}

/** Mobile representation of a table row: label/value stack instead of scroll. */
export function CardRow({
  title,
  subtitle,
  badges,
  fields,
  onClick,
  footer,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  badges?: React.ReactNode;
  fields: Array<{ label: string; value: React.ReactNode }>;
  onClick?: () => void;
  footer?: React.ReactNode;
}) {
  const Wrapper = onClick ? "button" : "div";
  return (
    <Wrapper
      {...(onClick ? { type: "button" as const, onClick } : {})}
      className={cn(
        "w-full border-b border-border/60 px-4 py-3 text-left last:border-0",
        onClick &&
          "transition-colors hover:bg-elevated/70 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm">{title}</div>
          {subtitle ? (
            <div className="truncate text-caption text-subtle-foreground">{subtitle}</div>
          ) : null}
        </div>
        {badges ? <div className="flex shrink-0 flex-wrap justify-end gap-1">{badges}</div> : null}
      </div>
      <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1.5">
        {fields.map((f) => (
          <div key={f.label} className="flex items-baseline justify-between gap-2">
            <dt className="text-caption uppercase tracking-wider text-subtle-foreground">
              {f.label}
            </dt>
            <dd className="numeric text-xs">{f.value}</dd>
          </div>
        ))}
      </dl>
      {footer ? <div className="mt-2">{footer}</div> : null}
    </Wrapper>
  );
}
