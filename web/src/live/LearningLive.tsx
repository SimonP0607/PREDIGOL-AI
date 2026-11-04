/**
 * APRENDIZAJE (Admin Console, plan F13): what PrediGol learns, in one page. Until F13 it was spread over four (Evolución, PrediGol Intelligence,
 * the AI decision layer, AI and research) and Memoria, and the calibration appeared in three of them.
 *
 *   CIERRE DEL DÍA    each closed day: the picks settled, the post-mortems and the revisions
 *   LO APRENDIDO      a day of PrediGol AI: what it learned, the improvements proposed (the owner answers here), the findings and the errors
 *   POST-MORTEMS      the one post-mortem of each selection of a day
 *   MEMORIA           the entities over time, the matches, the notes of the learning cycle and the findings of the research
 *   EXPERIMENTOS      every hypothesis by stage, the owner's proposals and the model code against its promotions
 *   CALIBRACIÓN       the calibrators (champions, challengers, retired), their gates, their promotions and their evaluations
 *   MERCADOS          the discovery of markets, the clock of the prices and the matrix of markets by family
 *   FAMILIAS          corners, cards, yellow cards and the goals of the halves deciding in shadow: what they said, how it was graded, what became of it
 *   LA IA FRENTE AL MODELO   the model alone, with rules, with the AI and the market on the same settled selections
 *   ATRIBUCIÓN        which agent, in which version, was right or wrong (computed from codes), the coverage of Gate B and the hypotheses per version
 *
 * Nothing here changes a rule, a model or a pick by itself: every change goes through an experiment, a backtest, shadow and the owner.
 */
import { useState } from "react";
import { t } from "@/lib/i18n";
import { shiftDay, todayKey } from "@/lib/time";
import { PageHeader } from "@/components/layout/PageHeader";
import { WarningBanner } from "@/components/primitives/Panel";
import { SegmentedTabs } from "@/components/system/Filters";
import { useUrlTab } from "@/lib/useUrlTab";
import { LEARNING_PATH, LEARNING_TABS } from "./adminAi";
import { useStrayRedirect } from "./useStrayRedirect";
import { ShadowBanner } from "./AiBits";
import { ComparisonPanel, ShadowTab } from "./AiLayerLive";
import { ShadowArmsPanel } from "./ShadowArmsPanel";
import { AttributionPanel } from "./AttributionPanel";
import { CloseTab } from "./AiResearchLive";
import { AI_TZ } from "./aiModel";
import { ExperimentsView, LearnedDay } from "./EvolutionLive";
import { FamiliesPanel } from "./FamiliesPanel";
import { CalibrationView, MarketsView } from "./IntelligenceLive";
import { MemoryViews } from "./MemoryLive";
import { PostmortemsPanel } from "./PostmortemsPanel";

export function LearningLive() {
  useStrayRedirect(LEARNING_PATH);
  const [tab, setTab] = useUrlTab(LEARNING_TABS, "close");
  // The AI's day is Bogotá's. The close and the post-mortems open on yesterday's, the last day whose results are all in, and share the day chosen.
  const today = todayKey(AI_TZ);
  const [day, setDay] = useState(() => shiftDay(today, -1));
  return (
    <div className="space-y-4" data-testid="learning-page">
      <PageHeader
        title={t("admin.pages.learning.title")}
        description={t("admin.pages.learning.description")}
      />
      <ShadowBanner />
      <WarningBanner tone="info">{t("ai.evolution.noAuto")}</WarningBanner>
      <SegmentedTabs
        tabs={LEARNING_TABS}
        value={tab}
        onChange={setTab}
        label={t("admin.learning.tabs.label")}
        format={(x) => t(`admin.learning.tabs.${x}`)}
      />
      {tab === "close" ? <CloseTab day={day} onDay={setDay} max={today} /> : null}
      {tab === "learned" ? <LearnedDay /> : null}
      {tab === "postmortems" ? <PostmortemsPanel day={day} onDay={setDay} max={today} /> : null}
      {tab === "memory" ? <MemoryViews /> : null}
      {tab === "experiments" ? <ExperimentsView /> : null}
      {tab === "calibration" ? <CalibrationView /> : null}
      {tab === "markets" ? <MarketsView /> : null}
      {tab === "families" ? <FamiliesPanel /> : null}
      {tab === "shadow" ? (
        <div className="space-y-4">
          <ComparisonPanel />
          <ShadowTab />
          <ShadowArmsPanel />
        </div>
      ) : null}
      {tab === "attribution" ? <AttributionPanel /> : null}
    </div>
  );
}
