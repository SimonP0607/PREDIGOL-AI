/**
 * Admin only: the research view of the fixture (models and predictions, capture timeline,
 * lineage, the audit chain, captured prices). Never rendered for a USER.
 */
import { ShieldCheck } from "lucide-react";
import { t } from "@/lib/i18n";
import { MatchCenterLive } from "@/live/MatchCenterLive";
import { ProviderPredictionPanel } from "./ProviderPredictionPanel";

export function AdvancedTab({ fixtureId }: { fixtureId: string }) {
  return (
    <div className="space-y-4">
      <p className="flex items-start gap-2 rounded-lg border border-info/30 bg-info-soft px-3 py-2 text-xs text-info">
        <ShieldCheck aria-hidden className="mt-px h-4 w-4 shrink-0" />
        {t("match.advanced.note")}
      </p>
      <ProviderPredictionPanel fixtureId={fixtureId} />
      <MatchCenterLive fixtureId={fixtureId} hideHeader />
    </div>
  );
}
