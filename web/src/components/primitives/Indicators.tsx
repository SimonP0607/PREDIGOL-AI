import { cn } from "@/lib/utils";
import { t } from "@/lib/i18n";
import { EMPTY, odds as fmtOdds, pct, signedPct } from "@/lib/format";

export function Numeric({
  children,
  className,
  muted,
}: {
  children: React.ReactNode;
  className?: string;
  muted?: boolean;
}) {
  return (
    <span className={cn("numeric text-sm", muted && "text-muted-foreground", className)}>
      {children}
    </span>
  );
}

export function EdgeIndicator({ value }: { value: number | null }) {
  if (value === null) return <Numeric muted>{EMPTY}</Numeric>;
  const positive = value > 0;
  return (
    <span
      className={cn(
        "numeric inline-flex items-center gap-1 text-sm",
        positive ? "text-positive" : value < 0 ? "text-negative" : "text-muted-foreground",
      )}
    >
      <span aria-hidden className="text-[0.7em]">
        {positive ? "▲" : value < 0 ? "▼" : "•"}
      </span>
      {signedPct(value, 2)}
    </span>
  );
}

export function EVIndicator({ value }: { value: number | null }) {
  if (value === null) return <Numeric muted>{EMPTY}</Numeric>;
  return (
    <span
      className={cn(
        "numeric text-sm",
        value > 0 ? "text-positive" : value < 0 ? "text-negative" : "text-muted-foreground",
      )}
    >
      {signedPct(value, 2)}
    </span>
  );
}

export function OddsCell({
  value,
  bookmaker,
  fair,
}: {
  value: number | null;
  bookmaker?: string | null;
  fair?: boolean;
}) {
  return (
    <span className="inline-flex flex-col leading-tight">
      <span className={cn("numeric text-sm", fair && "text-muted-foreground")}>
        {fmtOdds(value)}
      </span>
      {bookmaker ? <span className="text-caption text-subtle-foreground">{bookmaker}</span> : null}
    </span>
  );
}

export function LineValueIndicator({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <span className="text-caption text-subtle-foreground">{t("admin.ui.pendingValidation")}</span>
    );
  }
  return <EdgeIndicator value={value} />;
}

export function ProbabilityBar({
  value,
  variant = "model",
  label,
}: {
  value: number | null;
  variant?: "model" | "market";
  label?: string;
}) {
  const width = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2">
      {label ? (
        <span className="w-14 shrink-0 text-caption text-muted-foreground">{label}</span>
      ) : null}
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
        <div
          className={cn(
            "h-full rounded-full transition-[width] duration-500",
            variant === "model" ? "bg-primary" : "bg-info/70",
          )}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="numeric w-12 shrink-0 text-right text-xs">{pct(value, 1)}</span>
    </div>
  );
}

export function ProbabilityComparison({
  outcomes,
}: {
  outcomes: Array<{ label: string; model: number | null; market: number | null }>;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      {outcomes.map((o) => {
        const delta = o.model !== null && o.market !== null ? o.model - o.market : null;
        return (
          <div key={o.label} className="rounded-md border border-border bg-elevated/50 p-3">
            <div className="flex items-center justify-between">
              <span className="text-label text-muted-foreground">{o.label}</span>
              {delta !== null ? (
                <span
                  className={cn(
                    "numeric text-caption",
                    delta > 0
                      ? "text-positive"
                      : delta < 0
                        ? "text-negative"
                        : "text-muted-foreground",
                  )}
                >
                  {signedPct(delta, 1)}
                </span>
              ) : null}
            </div>
            <div className="mt-2 numeric-lg">{pct(o.model, 1)}</div>
            <div className="text-caption text-subtle-foreground">
              {t("admin.ui.modelProbability")}
            </div>
            <div className="mt-3 space-y-1.5">
              <ProbabilityBar value={o.model} variant="model" label={t("admin.ui.model")} />
              <ProbabilityBar value={o.market} variant="market" label={t("admin.ui.market")} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function FormStrip({ form }: { form: Array<"W" | "D" | "L"> }) {
  const tone = {
    W: "bg-positive-soft text-positive",
    D: "bg-muted text-muted-foreground",
    L: "bg-negative-soft text-negative",
  };
  return (
    <div className="flex gap-1" aria-label={t("admin.ui.form", { form: form.join(" ") })}>
      {form.map((r, i) => (
        <span
          key={i}
          className={cn(
            "numeric flex h-5 w-5 items-center justify-center rounded text-[0.65rem] font-semibold",
            tone[r],
          )}
        >
          {r}
        </span>
      ))}
    </div>
  );
}

export function TeamBadge({ code, name }: { code: string; name?: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="numeric flex h-6 w-6 items-center justify-center rounded border border-border bg-elevated text-[0.6rem] font-semibold text-muted-foreground">
        {code}
      </span>
      {name ? <span className="truncate text-sm">{name}</span> : null}
    </span>
  );
}

export function CompetitionBadge({ code, name }: { code: string; name: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="numeric rounded border border-border px-1 py-0.5 text-[0.6rem] text-muted-foreground">
        {code}
      </span>
      <span className="truncate text-sm text-muted-foreground">{name}</span>
    </span>
  );
}

export function ProvenanceChip({ label, value }: { label: string; value: string }) {
  return (
    <span className="inline-flex items-center gap-2 rounded border border-border bg-elevated/60 px-2 py-1">
      <span className="text-caption uppercase tracking-wider text-subtle-foreground">{label}</span>
      <span className="numeric text-xs">{value}</span>
    </span>
  );
}
