/**
 * Admin only: the research view of the fixture (models and predictions, the captures of its prices, capture timeline,
 * lineage, the audit chain, captured prices). Never rendered for a USER: the match page draws it only for the owner
 * (`showAdmin`), and the price captures check it again here.
 *
 * It also holds what left the reader's Resumen (plan Partidos y Match Center, section 5): PrediGol Intelligence's
 * evaluation view - the cards per market, the AI's «Lectura del día», the selections in evaluation and the note on the
 * context review - read with `preview=shadow`, which the API grants a SUPER_ADMIN alone.
 */
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { t } from "@/lib/i18n";
import { useAuth } from "@/lib/auth/AuthProvider";
import { live } from "@/lib/api/v1/queries";
import { MatchCenterLive } from "@/live/MatchCenterLive";
import { AnalysisBlock } from "./AnalysisBlock";
import { ProviderPredictionPanel } from "./ProviderPredictionPanel";
import { MatchCaptures } from "./CapturesStrip";

/** PrediGol Intelligence's evaluation view, once the match it belongs to is known (the page's own query, from its cache). */
function IntelligenceAudit({ fixtureId }: { fixtureId: string }) {
  const view = useQuery({ ...live.matchView(fixtureId), refetchInterval: false });
  const match = view.data?.data.match;
  if (!match) return null;
  return (
    <div className="space-y-2" data-testid="advanced-intelligence">
      <p className="px-1 text-caption text-subtle-foreground">{t("match.advanced.analysisNote")}</p>
      <AnalysisBlock ctx={{ fixtureId, match }} variant="audit" />
    </div>
  );
}

export function AdvancedTab({ fixtureId }: { fixtureId: string }) {
  const { showAdmin } = useAuth();
  return (
    <div className="space-y-4">
      <p className="flex items-start gap-2 rounded-lg border border-info/30 bg-info-soft px-3 py-2 text-xs text-info">
        <ShieldCheck aria-hidden className="mt-px h-4 w-4 shrink-0" />
        {t("match.advanced.note")}
      </p>
      <IntelligenceAudit fixtureId={fixtureId} />
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
