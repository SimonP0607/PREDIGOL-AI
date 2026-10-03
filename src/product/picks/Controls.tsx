/** Small controls shared by the Picks and Odds pages: filter chips and the admin-only shadow switch. */
import type { ReactNode } from "react";
import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";

export interface ChipOption<T extends string | number> {
  value: T;
  label: ReactNode;
  title?: string | undefined;
}

/** A row of toggle chips where exactly one is on. */
export function ChipGroup<T extends string | number>({
  label,
  value,
  options,
  onChange,
  className,
  testId,
}: {
  /** What the group chooses, for assistive technology. */
  label: string;
  value: T;
  options: ReadonlyArray<ChipOption<T>>;
  onChange: (value: T) => void;
  className?: string | undefined;
  testId?: string | undefined;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      data-testid={testId}
      className={cn("flex flex-wrap gap-1.5", className)}
    >
      {options.map((o) => {
        const on = o.value === value;
        return (
          <button
            key={String(o.value)}
            type="button"
            aria-pressed={on}
            title={o.title}
            onClick={() => onChange(o.value)}
            className={cn(
              "inline-flex h-9 items-center whitespace-nowrap rounded-full border px-3.5 text-xs font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              on
                ? "border-primary/50 bg-primary/12 text-primary"
                : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

/**
 * Admin only: lay the unqualified shadow picks out as the product would. Never rendered
 * for a USER, nor while a SUPER_ADMIN previews the product as one.
 */
export function ShadowToggle() {
  const auth = useAuth();
  if (!auth.showAdmin || !auth.can("admin.shadow_preview")) return null;
  const on = auth.shadowPreview;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      title={t("admin.shadowToggleHelp")}
      onClick={() => auth.setShadowPreview(!on)}
      data-testid="shadow-toggle"
      className={cn(
        "inline-flex h-9 items-center gap-2 rounded-full border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        on
          ? "border-info/50 bg-info-soft text-info"
          : "border-border bg-card text-muted-foreground hover:border-border-strong hover:text-foreground",
      )}
    >
      <FlaskConical aria-hidden className="h-3.5 w-3.5" />
      {t("admin.shadowToggle")}
      <span
        aria-hidden
        className={cn(
          "relative inline-flex h-4 w-7 shrink-0 items-center rounded-full transition-colors",
          on ? "bg-info" : "bg-border-strong",
        )}
      >
        <span
          className={cn(
            "h-3 w-3 rounded-full bg-background transition-transform",
            on ? "translate-x-3.5" : "translate-x-0.5",
          )}
        />
      </span>
    </button>
  );
}
