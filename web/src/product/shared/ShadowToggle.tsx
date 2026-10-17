/**
 * Admin only: lay the unqualified (shadow) picks out as the product would, to review the
 * design. Never rendered for a USER, nor while a SUPER_ADMIN previews as one.
 */
import { FlaskConical } from "lucide-react";
import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";

export function ShadowToggle({ className }: { className?: string | undefined }) {
  const auth = useAuth();
  if (!auth.showAdmin || !auth.can("admin.shadow_preview")) return null;
  const on = auth.shadowPreview;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      title={t("admin.shadowToggleHelp")}
      data-testid="shadow-toggle"
      onClick={() => auth.setShadowPreview(!on)}
      className={cn(
        "tap-y relative inline-flex min-h-9 items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        on
          ? "border-info/50 bg-info-soft text-info"
          : "border-border-strong bg-card text-muted-foreground hover:text-foreground",
        className,
      )}
    >
      <FlaskConical aria-hidden className="h-3.5 w-3.5 shrink-0" />
      <span>{t("admin.shadowToggle")}</span>
      <span
        aria-hidden
        className={cn(
          "relative h-4 w-7 shrink-0 rounded-full transition-colors",
          on ? "bg-info" : "bg-muted ring-1 ring-inset ring-border-strong",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-3 w-3 rounded-full bg-foreground shadow transition-[left]",
            on ? "left-3.5" : "left-0.5",
          )}
        />
      </span>
    </button>
  );
}
