/**
 * Admin only: the research view of the fixture (models and predictions, the captures of its prices, capture timeline,
 * lineage, the audit chain, captured prices). Never rendered for a USER: the match page draws it only for the owner
 * (`showAdmin`), and the price captures check it again here.
 */
import { ShieldCheck } from "lucide-react";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { MatchCenterLive } from "@/live/MatchCenterLive";
import { ProviderPredictionPanel } from "./ProviderPredictionPanel";
import { MatchCaptures } from "./CapturesStrip";

export function AdvancedTab({ fixtureId }: { fixtureId: string }) {
  const { showAdmin } = useAuth();
  return (
    <div className="space-y-4">
      <p className="flex items-start gap-2 rounded-lg border border-info/30 bg-info-soft px-3 py-2 text-xs text-info">
        <ShieldCheck aria-hidden className="mt-px h-4 w-4 shrink-0" />
        {t("match.advanced.note")}
      </p>
      <ProviderPredictionPanel fixtureId={fixtureId} />
      {showAdmin ? (
        <section aria-label={t("match.advanced.marketsTitle")} data-testid="advanced-captures">
          <h2 className="mb-2 font-display text-base font-semibold tracking-tight">
            {t("match.advanced.marketsTitle")}
          </h2>
          <MatchCaptures fixtureId={fixtureId} />
        </section>
      ) : null}
      <MatchCenterLive fixtureId={fixtureId} hideHeader />
    </div>
  );
}
