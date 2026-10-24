/**
 * The dossier's picker (Admin Console, plan F6): instead of a hand-typed match id, the matches of a Bogotá day - the
 * ones the AI studied first, each saying whether it has a packet and how much research its brief asked for - or, with a
 * text, the matches of the teams or competitions it names within 45 days of that day. A number is also looked up as a
 * match id, so what was typed before still works. Reading only.
 */
import { useEffect, useState } from "react";
import { t } from "@/lib/i18n";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { IntelPicker } from "@/lib/api/v1/types_intel";
import { shiftDay, todayKey } from "@/lib/time";
import { Note } from "./AiBits";
import { AI_TZ, bogotaDateTime, bogotaTime, dayLabel } from "./aiModel";
import { canSearch, pickerBadges, pickerParams } from "./intelMatch";

/** The value, ``ms`` after it stops changing: a query per pause in typing, not per key. */
function useDebounced<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return settled;
}

export function MatchPicker({
  fixture,
  onPick,
  onClose,
}: {
  /** The match being shown ("" when none). */
  fixture: string;
  onPick: (id: string) => void;
  /** Close the picker without choosing (offered once a match is shown). */
  onClose?: (() => void) | undefined;
}) {
  const [day, setDay] = useState<string | undefined>(undefined);
  const [text, setText] = useState("");
  const settled = useDebounced(text, 300);
  const q = useLiveQuery(live.intelMatches(pickerParams(settled, day)));
  const d = q.data?.data;
  return (
    <Panel
      title={t("intel.match.picker.title")}
      actions={
        onClose ? (
          <button
            type="button"
            className="tap-y relative rounded-md border border-border px-2.5 py-1 text-xs"
            onClick={onClose}
          >
            {t("intel.match.picker.close")}
          </button>
        ) : null
      }
    >
      <div className="space-y-3" data-testid="intel-picker">
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-caption uppercase tracking-wider text-subtle-foreground">
            {t("intel.match.picker.search")}
            <input
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={t("intel.match.picker.placeholder")}
              maxLength={60}
              className="h-8 min-h-11 w-full max-w-md rounded-md border border-border bg-card px-2 text-xs normal-case tracking-normal sm:min-h-8"
              data-testid="intel-picker-input"
            />
          </label>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className="tap-y relative rounded-md border border-border px-2.5 py-1 text-xs"
              onClick={() => setDay(shiftDay(d?.day ?? todayKey(AI_TZ), -1))}
            >
              ← {t("intel.day.prev")}
            </button>
            <span className="text-sm font-medium">{d ? dayLabel(d.day) : "…"}</span>
            <button
              type="button"
              className="tap-y relative rounded-md border border-border px-2.5 py-1 text-xs"
              onClick={() => setDay(shiftDay(d?.day ?? todayKey(AI_TZ), 1))}
            >
              {t("intel.day.next")} →
            </button>
            {day ? (
              <button
                type="button"
                className="tap-y relative rounded-md px-2 py-1 text-xs text-primary"
                onClick={() => setDay(undefined)}
              >
                {t("intel.day.today")}
              </button>
            ) : null}
          </div>
        </div>
        {text.trim() && !canSearch(text) ? <Note>{t("intel.match.picker.tooShort")}</Note> : null}
        {q.error ? <ApiErrorNotice error={q.error} /> : null}
        {q.isLoading ? <TableSkeleton rows={4} cols={3} /> : null}
        {d ? <PickerResults d={d} fixture={fixture} onPick={onPick} /> : null}
      </div>
    </Panel>
  );
}

/** What the picker found: the count line and the matches, each with the words of what the AI did about it. */
export function PickerResults({
  d,
  fixture,
  onPick,
}: {
  d: IntelPicker;
  fixture: string;
  onPick: (id: string) => void;
}) {
  const searching = d.mode === "search";
  return (
    <>
      <Note>
        {searching
          ? t("intel.match.picker.searchCount", {
              count: d.total,
              q: d.q ?? "",
              day: dayLabel(d.day),
            })
          : t("intel.match.picker.dayCount", { count: d.total, studied: d.with_packet })}
        {d.matches.length < d.total
          ? ` ${t("intel.match.picker.cut", { shown: d.matches.length, total: d.total })}`
          : ""}
      </Note>
      {d.matches.length === 0 ? (
        <Note>{t("intel.match.picker.none")}</Note>
      ) : (
        <ul className="divide-y divide-border/60 rounded-md border border-border">
          {d.matches.map((m) => {
            const selected = String(m.fixture_id) === fixture;
            return (
              <li key={m.fixture_id}>
                <button
                  type="button"
                  aria-pressed={selected}
                  onClick={() => onPick(String(m.fixture_id))}
                  data-testid="intel-picker-row"
                  className={`flex w-full min-w-0 flex-wrap items-start gap-x-3 gap-y-1 px-3 py-2 text-left text-sm transition-colors pointer-coarse:min-h-11 hover:bg-elevated/50 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ring ${
                    selected ? "bg-primary/8" : ""
                  }`}
                >
                  <span className="numeric shrink-0 pt-0.5 text-xs text-muted-foreground sm:w-28">
                    {searching ? bogotaDateTime(m.kickoff_at) : bogotaTime(m.kickoff_at)}
                  </span>
                  <span className="min-w-[10rem] flex-1 break-words font-medium">
                    {m.home} - {m.away}
                    <span className="ml-2 text-xs font-normal text-subtle-foreground">
                      {m.competition}
                      {m.country ? ` · ${m.country}` : ""}
                    </span>
                  </span>
                  <span className="flex basis-full flex-wrap items-center gap-1 sm:basis-auto">
                    {pickerBadges(m).map((b) => (
                      <StatusBadge key={b.key} tone={b.tone} dot={false}>
                        {b.text}
                      </StatusBadge>
                    ))}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
