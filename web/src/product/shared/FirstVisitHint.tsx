/**
 * A page's first-visit hint (plan UX, A13; section 20): one short card the first time a reader opens Picks, a match, the
 * parlays or Mis picks, dismissed with a tap and never shown again («Nunca: modales que vuelven en cada visita»). In the
 * page's flow, never over it; nothing to do but read it or dismiss it.
 */
import { Lightbulb, X } from "lucide-react";
import type { HintKey } from "@/lib/api/v1/types_favorites";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useHint } from "@/product/favorites/onboarding";

export function FirstVisitHint({ hint, className }: { hint: HintKey; className?: string }) {
  const { shown, dismiss } = useHint(hint);
  if (!shown) return null;
  return (
    <aside
      aria-label={t("onboarding.hint.label")}
      data-testid="first-visit-hint"
      data-hint={hint}
      className={cn(
        "flex items-start gap-3 rounded-xl border border-gold/40 bg-gold-soft px-4 py-3 text-sm",
        className,
      )}
    >
      <Lightbulb aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-gold-strong" />
      <p className="min-w-0 flex-1 leading-relaxed text-foreground/90">
        {t(`onboarding.hint.${hint}`)}
      </p>
      <button
        type="button"
        onClick={dismiss}
        data-testid="hint-dismiss"
        className="tap relative -mr-1 inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-caption font-semibold text-gold-strong hover:bg-gold/10 pointer-coarse:min-h-11"
      >
        <X aria-hidden className="h-3.5 w-3.5" />
        {t("onboarding.hint.dismiss")}
      </button>
    </aside>
  );
}
