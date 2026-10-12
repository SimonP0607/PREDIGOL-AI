import { useRef } from "react";
import { Search, SlidersHorizontal, X } from "lucide-react";
import { t } from "@/lib/i18n";
import { useScrollCue } from "@/lib/scrollCue";
import { cn } from "@/lib/utils";

export interface Option {
  value: string;
  label: string;
}

export function FilterBar({
  children,
  meta,
  onReset,
  className,
}: {
  children: React.ReactNode;
  meta?: React.ReactNode;
  onReset?: () => void;
  className?: string;
}) {
  return (
    <div className={cn("surface-panel flex flex-wrap items-end gap-2 px-3 py-2.5", className)}>
      <SlidersHorizontal
        aria-hidden
        className="mb-1.5 hidden h-3.5 w-3.5 text-subtle-foreground sm:block"
      />
      {children}
      <div className="ml-auto flex items-center gap-3 pb-0.5">
        {meta}
        {onReset ? (
          <button
            type="button"
            onClick={onReset}
            className="inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-caption text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          >
            <X aria-hidden className="h-3 w-3" />
            Reset
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function SelectFilter({
  label,
  value,
  options,
  onChange,
  className,
}: {
  label: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  className?: string;
}) {
  const id = `filter-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={id} className="text-caption uppercase tracking-wider text-subtle-foreground">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="h-8 rounded-md border border-border bg-card px-2 text-xs text-foreground focus:border-border-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

export function SearchFilter({
  label: labelProp,
  value,
  onChange,
  placeholder,
  className,
}: {
  label?: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const label = labelProp ?? t("admin.ui.search");
  const id = `search-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={id} className="text-caption uppercase tracking-wider text-subtle-foreground">
        {label}
      </label>
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-subtle-foreground"
        />
        <input
          id={id}
          type="search"
          value={value}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
          className="h-8 w-full rounded-md border border-border bg-card pl-7 pr-2 text-xs placeholder:text-subtle-foreground focus:border-border-strong focus:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
    </div>
  );
}

export function NumberFilter({
  label,
  value,
  onChange,
  step = 0.5,
  min = 0,
  max = 20,
  suffix = "%",
  className,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  min?: number;
  max?: number;
  suffix?: string;
  className?: string;
}) {
  const id = `range-${label.toLowerCase().replace(/\s+/g, "-")}`;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={id} className="text-caption uppercase tracking-wider text-subtle-foreground">
        {label} <span className="numeric text-foreground">{`${value}${suffix}`}</span>
      </label>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-8 w-full accent-[var(--primary)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
    </div>
  );
}

export function SegmentedTabs<T extends string>({
  tabs,
  value,
  onChange,
  counts,
  label,
  className,
  format,
}: {
  tabs: readonly T[];
  value: T;
  onChange: (value: T) => void;
  counts?: Partial<Record<T, number>>;
  label: string;
  className?: string;
  /** Display text for a tab value; the value itself when omitted. */
  format?: (value: T) => string;
}) {
  const strip = useRef<HTMLDivElement>(null);
  useScrollCue(strip);
  return (
    <div
      ref={strip}
      role="tablist"
      aria-label={label}
      className={cn(
        "scroll-strip flex w-full gap-1 rounded-md border border-border bg-card p-1",
        className,
      )}
    >
      {tabs.map((t) => {
        const active = t === value;
        return (
          <button
            key={t}
            role="tab"
            type="button"
            aria-selected={active}
            onClick={() => onChange(t)}
            className={cn(
              // Touch: 36 px drawn, 44 touched (tap-y reaches the strip's 4 px padding on each side).
              "tap-y relative flex shrink-0 items-center gap-1.5 rounded px-2.5 py-1 text-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring pointer-coarse:min-h-9",
              active
                ? "bg-primary/12 text-primary"
                : "text-muted-foreground hover:bg-elevated hover:text-foreground",
            )}
          >
            {format ? format(t) : t}
            {counts?.[t] !== undefined ? (
              <span className="numeric text-caption opacity-70">{counts[t]}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}

export function ToggleFilter({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer select-none items-center gap-2 pb-1 text-xs text-muted-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="h-3.5 w-3.5 rounded border-border accent-[var(--primary)] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
      {label}
    </label>
  );
}
