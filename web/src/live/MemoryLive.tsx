/**
 * MEMORIA (Admin Console, plan F8; a tab of Aprendizaje since plan F13): everything PrediGol has learned, in one place. It used to be in four
 * (a tab of PrediGol Intelligence, a tab of the AI decision layer, a tab of the AI analyst and a panel of Evolución) and the post-mortems were in a fifth.
 *
 *   ENTIDADES        teams, leagues, markets, referees, coaches and players over time, with version, confidence and evidence
 *   PARTIDOS         the matches PrediGol looked at, before and after
 *   NOTAS            what the AI's daily learning cycle wrote down
 *   HALLAZGOS        what the model research concluded
 *
 * The post-mortem of each selection of a day has a tab of its own (PostmortemsPanel). Reading only: nothing here changes a pick, a
 * probability or a model.
 */
import { t } from "@/lib/i18n";
import { SegmentedTabs } from "@/components/system/Filters";
import { MEMORY_VIEWS, VIEW_PARAM } from "./adminAi";
import { Note } from "./AiBits";
import { EntityMemory } from "./MemoryEntities";
import { LearningNotes, ResearchFindings } from "./MemoryNotes";
import { MatchMemoryPanel } from "./MatchMemoryPanel";
import { useUrlTab } from "@/lib/useUrlTab";

export function MemoryViews() {
  const [view, setView] = useUrlTab(MEMORY_VIEWS, "entities", VIEW_PARAM);
  return (
    <div className="space-y-4">
      <Note>{t("memory.intro")}</Note>
      <SegmentedTabs
        tabs={MEMORY_VIEWS}
        value={view}
        onChange={setView}
        label={t("memory.tabs.label")}
        format={(x) => t(`admin.learning.memoryViews.${x}`)}
      />
      {view === "entities" ? <EntityMemory /> : null}
      {view === "matches" ? <MatchMemoryPanel /> : null}
      {view === "notes" ? <LearningNotes /> : null}
      {view === "findings" ? <ResearchFindings /> : null}
    </div>
  );
}
