/**
 * MEMORIA (Admin Console, plan F8): everything PrediGol has learned, in one place. It used to be in four (a tab of PrediGol Intelligence,
 * a tab of the AI decision layer, a tab of the AI analyst and a panel of Evolución) and the post-mortems were in a fifth.
 *
 *   ENTIDADES        teams, leagues, markets, referees, coaches and players over time, with version, confidence and evidence
 *   PARTIDOS         the matches PrediGol looked at, before and after
 *   POST-MORTEMS     the one post-mortem of each selection of a day
 *   NOTAS            what the AI's daily learning cycle wrote down
 *   HALLAZGOS        what the model research concluded
 *
 * Reading only: nothing here changes a pick, a probability or a model.
 */
import { useState } from "react";
import { t } from "@/lib/i18n";
import { shiftDay, todayKey } from "@/lib/time";
import { PageHeader } from "@/components/layout/PageHeader";
import { SegmentedTabs } from "@/components/system/Filters";
import { Note, ShadowBanner } from "./AiBits";
import { AI_TZ } from "./aiModel";
import { EntityMemory } from "./MemoryEntities";
import { LearningNotes, ResearchFindings } from "./MemoryNotes";
import { MatchMemoryPanel } from "./MatchMemoryPanel";
import { PostmortemsPanel } from "./PostmortemsPanel";
import { useUrlTab } from "@/lib/useUrlTab";

export const MEMORY_TABS = ["entities", "matches", "postmortems", "events", "research"] as const;
export type MemoryTab = (typeof MEMORY_TABS)[number];

export function MemoryLive() {
  const [tab, setTab] = useUrlTab(MEMORY_TABS, "entities");
  // The AI's day is Bogotá's; the post-mortems open on yesterday's, the last day whose results are all in.
  const today = todayKey(AI_TZ);
  const [day, setDay] = useState(() => shiftDay(today, -1));
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.memory.title")}
        description={t("admin.pages.memory.description")}
      />
      <ShadowBanner />
      <Note>{t("memory.intro")}</Note>
      <SegmentedTabs
        tabs={MEMORY_TABS}
        value={tab}
        onChange={setTab}
        label={t("memory.tabs.label")}
        format={(x) => t(`memory.tabs.${x}`)}
      />
      {tab === "entities" ? <EntityMemory /> : null}
      {tab === "matches" ? <MatchMemoryPanel /> : null}
      {tab === "postmortems" ? <PostmortemsPanel day={day} onDay={setDay} max={today} /> : null}
      {tab === "events" ? <LearningNotes /> : null}
      {tab === "research" ? <ResearchFindings /> : null}
    </div>
  );
}
