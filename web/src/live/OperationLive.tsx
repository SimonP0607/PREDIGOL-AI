/**
 * OPERACIÓN (Admin Console, plan F13): the day of the AI, in one page. Until F13 it was spread over three (PrediGol Intelligence, the AI decision layer
 * and AI and research) and what it costs appeared in all of them.
 *
 *   EL DÍA        what was analysed and what became of every candidate, how deep the AI went, the picks of the day and the day's learning report
 *   DECISIONES    every decision whole: the ten filters, the score and the stake, the context, the model, the outcome
 *   PARTIDO       the dossier of a match, found by a search and not by typing an id, with its narrative
 *   TRABAJO IA    the mode and the owner's "run now", and the AI's own work: today's matches, the research, the research by entity and topic (plan IA,
 *                 phase 2), the reviews, the evidence, the sources
 *   AGENTES       the agents of the plan: the registry against the code, the engine of each family, the state of the matches, the queue, the audit
 *   COSTOS        the budget, the models, the pace, the efficiency of today and everything the periods cost
 *   EJECUCIONES   what ran and the leakage audit
 *
 * What is learned from it (the close of the day, the memory, the experiments, the calibration, the markets) is in Aprendizaje. Reading only, apart
 * from the owner's "run now": nothing here changes a pick, a probability or a model.
 */
import { useState } from "react";
import { t } from "@/lib/i18n";
import { todayKey } from "@/lib/time";
import { PageHeader } from "@/components/layout/PageHeader";
import { WarningBanner } from "@/components/primitives/Panel";
import { SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { useUrlTab } from "@/lib/useUrlTab";
import { AI_VIEWS, OPERATION_PATH, OPERATION_TABS, VIEW_PARAM } from "./adminAi";
import { useStrayRedirect } from "./useStrayRedirect";
import { CostsView } from "./AiCosts";
import { ShadowBanner } from "./AiBits";
import { EvidenceTab, ReviewsTab, StatusStrip } from "./AiLayerLive";
import { ResearchTab, SourcesTab, TodayTab } from "./AiResearchLive";
import { AgentsView } from "./AgentsLive";
import { TopicsView } from "./TopicsLive";
import { AI_TZ } from "./aiModel";
import { DayView, DecisionDetail, DecisionsView, MatchView, RunsView } from "./IntelligenceLive";

/** TRABAJO IA: the state of the AI layer and the owner's "run now", then the views of what the AI did. */
function AiWork() {
  const [view, setView] = useUrlTab(AI_VIEWS, "today", VIEW_PARAM);
  // The AI's day is Bogotá's, not the browser's UTC date.
  const today = todayKey(AI_TZ);
  const [day, setDay] = useState(today);
  const q = useLiveQuery(live.aiOverview);
  const o = q.data?.data ?? null;
  return (
    <div className="space-y-4" data-testid="operation-ai">
      {o && !o.settings.llm_configured ? (
        <WarningBanner tone="info">
          {t("ai.layer.noModel", { missing: o.settings.missing.join(", ") || "—" })}
        </WarningBanner>
      ) : null}
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <StatusStrip o={o} />
      <SegmentedTabs
        tabs={AI_VIEWS}
        value={view}
        onChange={setView}
        label={t("admin.operation.aiViews.label")}
        format={(x) => t(`admin.operation.aiViews.${x}`)}
      />
      {view === "today" ? <TodayTab day={day} onDay={setDay} max={today} /> : null}
      {view === "research" ? <ResearchTab day={day} onDay={setDay} max={today} /> : null}
      {view === "topics" ? <TopicsView /> : null}
      {view === "reviews" ? <ReviewsTab /> : null}
      {view === "evidence" ? <EvidenceTab /> : null}
      {view === "sources" ? <SourcesTab /> : null}
    </div>
  );
}

export function OperationLive() {
  useStrayRedirect(OPERATION_PATH);
  const [tab, setTab] = useUrlTab(OPERATION_TABS, "day");
  const [open, setOpen] = useState<number>(0);
  const [fixture, setFixture] = useState<string>("");
  const openDecision = (id: number) => {
    if (id > 0) setOpen(id);
  };
  const toMatch = (f: number) => {
    setFixture(String(f));
    setTab("match");
  };
  return (
    <div className="space-y-4" data-testid="operation-page">
      <PageHeader
        title={t("admin.pages.operation.title")}
        description={t("admin.pages.operation.description")}
      />
      <ShadowBanner />
      <SegmentedTabs
        tabs={OPERATION_TABS}
        value={tab}
        onChange={setTab}
        label={t("admin.operation.tabs.label")}
        format={(x) => t(`admin.operation.tabs.${x}`)}
      />
      {open > 0 ? <DecisionDetail id={open} onClose={() => setOpen(0)} onMatch={toMatch} /> : null}
      {tab === "day" ? <DayView onOpen={openDecision} /> : null}
      {tab === "decisions" ? <DecisionsView onOpen={openDecision} /> : null}
      {tab === "match" ? (
        <MatchView fixture={fixture} setFixture={setFixture} onOpen={openDecision} />
      ) : null}
      {tab === "ai" ? <AiWork /> : null}
      {tab === "agents" ? <AgentsView /> : null}
      {tab === "costs" ? <CostsView /> : null}
      {tab === "runs" ? <RunsView /> : null}
    </div>
  );
}
