/** Referees as people (plan F3): who they are, the doubts the rules could not settle, and one referee's page with its decisions. */
import { useDeferredValue, useState } from "react";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricCard, Panel } from "@/components/primitives/Panel";
import { TableShell, TableSkeleton, TD, TH, THead, TRow } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { FilterBar, SearchFilter, SelectFilter } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  PairStatus,
  RefereeCounts,
  RefereeDetail,
  RefereeEvent,
  RefereePair,
  RefereeSummary,
} from "@/lib/api/v1/types_referees";
import { t } from "@/lib/i18n";
import { localInt } from "@/lib/i18n/format";
import { formatDateTime } from "@/lib/time";
import { EmptyState } from "@/product/shared/States";
import { ratio, utcDate } from "./format";
import { PairDecision } from "./RefereeDecisions";
import { useRefereeAction } from "./useRefereeAction";
import {
  basisLabel,
  canUndo,
  pickedAliases,
  reasonLabel,
  REASONS,
  settledShare,
} from "./refereeText";

const PAGE = 50;

function RefereeLink({ id, name }: { id: number; name: string }) {
  return (
    <Link
      to="/admin/referees/$refereeId"
      params={{ refereeId: String(id) }}
      className="hover:text-primary"
    >
      {name}
    </Link>
  );
}

function Counts({ counts, queueOpen }: { counts: RefereeCounts; queueOpen: number }) {
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label={t("referees.counts.people")} value={localInt(counts.referees_active)} />
        <MetricCard label={t("referees.counts.spellings")} value={localInt(counts.aliases)} />
        <MetricCard
          label={t("referees.counts.matches")}
          value={localInt(counts.fixtures_with_referee)}
        />
        <MetricCard
          label={t("referees.counts.settled")}
          value={ratio(settledShare(counts), 1)}
          hint={t("referees.counts.settledHint")}
          tone={counts.matches_with_a_doubt > 0 ? "warning" : "positive"}
        />
        <MetricCard
          label={t("referees.counts.queue")}
          value={localInt(queueOpen)}
          tone={queueOpen > 0 ? "warning" : "positive"}
        />
        <MetricCard
          label={t("referees.counts.doubtMatches")}
          value={localInt(counts.matches_with_a_doubt)}
        />
        <MetricCard
          label={t("referees.counts.problems")}
          value={counts.problems.length ? counts.problems.join(", ") : t("referees.counts.none")}
          tone={counts.problems.length ? "negative" : "positive"}
        />
      </div>
    </div>
  );
}

function Pager({
  offset,
  total,
  onChange,
}: {
  offset: number;
  total: number;
  onChange: (o: number) => void;
}) {
  if (total <= PAGE) return null;
  const btn = "rounded border border-border px-2 py-0.5 text-xs hover:bg-muted disabled:opacity-40";
  return (
    <div className="mt-3 flex items-center justify-between text-xs text-muted-foreground">
      <button
        type="button"
        className={btn}
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - PAGE))}
      >
        ‹
      </button>
      <span>
        {offset + 1}–{Math.min(total, offset + PAGE)} / {localInt(total)}
      </span>
      <button
        type="button"
        className={btn}
        disabled={offset + PAGE >= total}
        onClick={() => onChange(offset + PAGE)}
      >
        ›
      </button>
    </div>
  );
}

function PeopleTable({ rows }: { rows: RefereeSummary[] }) {
  if (!rows.length) return <EmptyState compact title={t("referees.list.empty")} />;
  return (
    <TableShell>
      <THead>
        <TH>{t("referees.list.headers.name")}</TH>
        <TH>{t("referees.list.headers.country")}</TH>
        <TH align="right">{t("referees.list.headers.matches")}</TH>
        <TH>{t("referees.list.headers.first")}</TH>
        <TH>{t("referees.list.headers.last")}</TH>
      </THead>
      <tbody>
        {rows.map((r) => (
          <TRow key={r.id}>
            <TD className="text-sm">
              <RefereeLink id={r.id} name={r.name} />
              {r.name_locked ? (
                <span
                  className="ml-1.5 text-caption text-subtle-foreground"
                  title={t("referees.list.locked")}
                >
                  ●
                </span>
              ) : null}
            </TD>
            <TD className="text-xs text-muted-foreground">
              {r.country ?? t("referees.list.unknownCountry")}
            </TD>
            <TD align="right" className="text-xs tabular-nums">
              {localInt(r.matches)}
            </TD>
            <TD className="text-xs text-muted-foreground">{utcDate(r.first_match)}</TD>
            <TD className="text-xs text-muted-foreground">{utcDate(r.last_match)}</TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function PairRow({ pair }: { pair: RefereePair }) {
  return (
    <TRow>
      <TD className="text-sm">
        <div className="flex flex-wrap items-center gap-x-2">
          <RefereeLink id={pair.a.id} name={pair.a.name} />
          <span className="text-caption text-subtle-foreground">
            {t("referees.queue.matches", { n: pair.a.matches })}
          </span>
          <span className="text-subtle-foreground">⟷</span>
          <RefereeLink id={pair.b.id} name={pair.b.name} />
          <span className="text-caption text-subtle-foreground">
            {t("referees.queue.matches", { n: pair.b.matches })}
          </span>
        </div>
        {pair.status !== "open" && pair.decided_by ? (
          <div className="text-caption text-subtle-foreground">
            {t("referees.queue.decidedBy", { who: pair.decided_by })}
            {pair.decided_at ? ` · ${formatDateTime(pair.decided_at)}` : ""}
          </div>
        ) : null}
      </TD>
      <TD className="text-xs">{reasonLabel(pair.reason)}</TD>
      <TD align="right" className="text-xs tabular-nums">
        {ratio(pair.score, 0)}
      </TD>
      <TD align="right" className="text-xs tabular-nums">
        {localInt(pair.impact)}
      </TD>
      <TD className="text-xs">
        <PairDecision a={pair.a} b={pair.b} status={pair.status} />
      </TD>
    </TRow>
  );
}

function QueueTab() {
  const [status, setStatus] = useState<PairStatus>("open");
  const [reason, setReason] = useState("");
  const [offset, setOffset] = useState(0);
  const q = useLiveQuery(live.refereeQueue({ status, reason: reason || undefined, offset }));
  const data = q.data?.data;
  return (
    <div className="space-y-3">
      <FilterBar>
        <SelectFilter
          label={t("referees.queue.filter.status")}
          value={status}
          onChange={(v) => {
            setStatus(v as PairStatus);
            setOffset(0);
          }}
          options={(["open", "rejected", "merged"] as const).map((s) => ({
            value: s,
            label: t(`referees.queue.status.${s}`),
          }))}
        />
        <SelectFilter
          label={t("referees.queue.filter.reason")}
          value={reason}
          onChange={(v) => {
            setReason(v);
            setOffset(0);
          }}
          options={[
            { value: "", label: t("referees.queue.filter.all") },
            ...REASONS.map((r) => ({ value: r, label: reasonLabel(r) })),
          ]}
        />
      </FilterBar>
      {q.isLoading ? (
        <TableSkeleton rows={6} cols={5} />
      ) : q.isError ? (
        <ApiErrorNotice error={q.error} />
      ) : !data || !data.items.length ? (
        <EmptyState
          compact
          title={t(status === "open" ? "referees.queue.empty.open" : "referees.queue.empty.other")}
        />
      ) : (
        <>
          <TableShell>
            <THead>
              <TH>{t("referees.queue.headers.pair")}</TH>
              <TH>{t("referees.queue.headers.reason")}</TH>
              <TH align="right">{t("referees.queue.headers.score")}</TH>
              <TH align="right">{t("referees.queue.headers.impact")}</TH>
              <TH>{t("referees.queue.headers.decision")}</TH>
            </THead>
            <tbody>
              {data.items.map((p) => (
                <PairRow key={p.id} pair={p} />
              ))}
            </tbody>
          </TableShell>
          <Pager offset={offset} total={data.total} onChange={setOffset} />
        </>
      )}
    </div>
  );
}

function PeopleTab({
  search,
  offset,
  setOffset,
}: {
  search: string;
  offset: number;
  setOffset: (o: number) => void;
}) {
  const q = useLiveQuery(live.referees({ q: search.trim() || undefined, offset }));
  const data = q.data?.data;
  if (q.isLoading) return <TableSkeleton rows={8} cols={5} />;
  if (q.isError) return <ApiErrorNotice error={q.error} />;
  if (!data) return <EmptyState compact title={t("referees.list.empty")} />;
  return (
    <>
      <PeopleTable rows={data.items} />
      <Pager offset={offset} total={data.total} onChange={setOffset} />
    </>
  );
}

export function RefereesLive() {
  const [tab, setTab] = useState<"people" | "queue">("people");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const deferred = useDeferredValue(search);
  const head = useLiveQuery(live.referees({ offset: 0 }));
  const counts = head.data?.data;
  const tabClass = (on: boolean) =>
    `rounded-md px-3 py-1 text-sm ${on ? "bg-primary/12 text-primary" : "text-muted-foreground hover:bg-muted"}`;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: t("admin.nav.referees") }]}
        title={t("referees.title")}
        description={t("referees.description")}
      />
      {counts ? <Counts counts={counts.counts} queueOpen={counts.queue_open} /> : null}
      <div role="tablist" className="flex gap-1">
        <button
          type="button"
          role="tab"
          aria-selected={tab === "people"}
          className={tabClass(tab === "people")}
          onClick={() => setTab("people")}
        >
          {t("referees.tabs.people")}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={tab === "queue"}
          className={tabClass(tab === "queue")}
          onClick={() => setTab("queue")}
        >
          {t("referees.tabs.queue")}
          {counts && counts.queue_open > 0 ? ` (${localInt(counts.queue_open)})` : ""}
        </button>
      </div>
      {tab === "people" ? (
        <Panel>
          <div className="mb-3 max-w-sm">
            <SearchFilter
              label={t("referees.list.search")}
              value={search}
              onChange={(v) => {
                setSearch(v);
                setOffset(0);
              }}
              placeholder={t("referees.list.search")}
            />
          </div>
          <PeopleTab search={deferred} offset={offset} setOffset={setOffset} />
        </Panel>
      ) : (
        <Panel>
          <QueueTab />
        </Panel>
      )}
    </div>
  );
}

function Rename({ d }: { d: RefereeDetail }) {
  const [name, setName] = useState(d.referee.name);
  const m = useRefereeAction();
  const btn = "rounded border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50";
  return (
    <Panel title={t("referees.detail.rename.title")}>
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={120}
          placeholder={t("referees.detail.rename.placeholder")}
          aria-label={t("referees.detail.rename.title")}
          className="min-w-[14rem] flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
        />
        <button
          type="button"
          className={btn}
          disabled={m.isPending || !name.trim() || name.trim() === d.referee.name}
          onClick={() => m.mutate({ kind: "rename", id: d.referee.id, name: name.trim() })}
        >
          {t("referees.detail.rename.save")}
        </button>
        {d.referee.name_locked ? (
          <button
            type="button"
            className={btn}
            disabled={m.isPending}
            onClick={() => m.mutate({ kind: "rename", id: d.referee.id, name: null })}
          >
            {t("referees.detail.rename.rules")}
          </button>
        ) : null}
      </div>
      {d.referee.name_locked ? (
        <div className="mt-2 text-caption text-subtle-foreground">
          {t("referees.detail.rename.locked")}
        </div>
      ) : null}
      {m.isError ? <ApiErrorNotice className="mt-2" error={m.error} /> : null}
    </Panel>
  );
}

function Aliases({ d }: { d: RefereeDetail }) {
  const [ticked, setTicked] = useState<ReadonlySet<number>>(new Set());
  const [newName, setNewName] = useState("");
  const m = useRefereeAction(() => {
    setTicked(new Set());
    setNewName("");
  });
  const ids = d.aliases.map((a) => a.id);
  const picked = pickedAliases(ids, ticked);
  const all = ids.length > 0 && picked.length === ids.length;
  return (
    <Panel
      title={t("referees.detail.aliases.title")}
      subtitle={t("referees.detail.aliases.subtitle")}
    >
      <TableShell>
        <THead>
          <TH>{""}</TH>
          <TH>{t("referees.detail.aliases.headers.display")}</TH>
          <TH>{t("referees.detail.aliases.headers.basis")}</TH>
          <TH align="right">{t("referees.detail.aliases.headers.matches")}</TH>
          <TH>{t("referees.detail.aliases.headers.last")}</TH>
        </THead>
        <tbody>
          {d.aliases.map((a) => (
            <TRow key={a.id}>
              <TD>
                <input
                  type="checkbox"
                  checked={ticked.has(a.id)}
                  aria-label={t("referees.detail.aliases.select", { name: a.display })}
                  onChange={(e) => {
                    const next = new Set(ticked);
                    if (e.target.checked) next.add(a.id);
                    else next.delete(a.id);
                    setTicked(next);
                  }}
                />
              </TD>
              <TD className="text-sm">
                {a.display}
                <div className="text-caption text-subtle-foreground">
                  {a.country ?? t("referees.list.unknownCountry")}
                </div>
              </TD>
              <TD className="text-xs text-muted-foreground">{basisLabel(a.basis)}</TD>
              <TD align="right" className="text-xs tabular-nums">
                {localInt(a.matches)}
              </TD>
              <TD className="text-xs text-muted-foreground">{utcDate(a.last)}</TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
      {d.aliases.length > 1 ? (
        <div className="mt-3 space-y-2">
          <div className="text-caption text-subtle-foreground">
            {t("referees.detail.split.hint")}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              maxLength={120}
              placeholder={t("referees.detail.split.name")}
              aria-label={t("referees.detail.split.name")}
              className="min-w-[14rem] flex-1 rounded border border-border bg-background px-2 py-1 text-sm"
            />
            <button
              type="button"
              className="rounded border border-border px-2 py-1 text-xs hover:bg-muted disabled:opacity-50"
              disabled={m.isPending || picked.length === 0 || all}
              onClick={() =>
                m.mutate({
                  kind: "split",
                  id: d.referee.id,
                  aliasIds: picked,
                  ...(newName.trim() ? { name: newName.trim() } : {}),
                })
              }
            >
              {t("referees.detail.split.button")}
            </button>
          </div>
          {m.isError ? <ApiErrorNotice error={m.error} /> : null}
        </div>
      ) : null}
    </Panel>
  );
}

function Events({ events }: { events: RefereeEvent[] }) {
  const m = useRefereeAction();
  return (
    <Panel
      title={t("referees.detail.events.title")}
      subtitle={t("referees.detail.events.subtitle")}
    >
      {!events.length ? (
        <EmptyState compact title={t("referees.detail.events.empty")} />
      ) : (
        <TableShell>
          <THead>
            <TH>{t("referees.detail.events.headers.when")}</TH>
            <TH>{t("referees.detail.events.headers.who")}</TH>
            <TH>{t("referees.detail.events.headers.action")}</TH>
            <TH>{""}</TH>
          </THead>
          <tbody>
            {events.map((e) => (
              <TRow key={e.id}>
                <TD className="text-xs text-muted-foreground">{formatDateTime(e.at)}</TD>
                <TD className="text-xs">{e.actor}</TD>
                <TD className="text-xs">
                  {t(`referees.action.names.${e.action}`)}
                  {e.undone_by !== null ? (
                    <span className="ml-2">
                      <StatusBadge tone="neutral">{t("referees.detail.events.undone")}</StatusBadge>
                    </span>
                  ) : null}
                </TD>
                <TD className="text-xs">
                  {canUndo(e) ? (
                    <button
                      type="button"
                      className="rounded border border-border px-1.5 py-0.5 text-[11px] hover:bg-muted disabled:opacity-50"
                      disabled={m.isPending}
                      onClick={() => m.mutate({ kind: "undo", eventId: e.id })}
                    >
                      {t("referees.action.undo")}
                    </button>
                  ) : null}
                </TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      )}
      {m.isError ? <ApiErrorNotice className="mt-2" error={m.error} /> : null}
    </Panel>
  );
}

export function RefereeLive({ refereeId }: { refereeId: string }) {
  const q = useLiveQuery(live.referee(refereeId));
  const crumbs = [{ label: t("admin.nav.referees"), to: "/admin/referees" as const }];
  if (q.isLoading) return <TableSkeleton rows={8} cols={5} />;
  const missing = q.isError && (q.error as { status?: number }).status === 404;
  if (q.isError && !missing) return <ApiErrorNotice error={q.error} />;
  const d = q.data?.data;
  if (missing || !d) {
    return (
      <div className="space-y-4">
        <PageHeader breadcrumb={crumbs} title={t("referees.detail.notFound")} />
      </div>
    );
  }
  const r = d.referee;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[...crumbs, { label: r.name }]}
        title={r.name}
        description={t("referees.detail.subtitle", {
          matches: localInt(r.matches),
          country: r.country ?? t("referees.list.unknownCountry"),
        })}
        actions={
          r.status === "merged" && r.merged_into !== null ? (
            <StatusBadge tone="neutral">
              {t("referees.detail.mergedInto")}{" "}
              <RefereeLink id={r.merged_into} name={`#${r.merged_into}`} />
            </StatusBadge>
          ) : undefined
        }
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Rename key={`${r.id}:${r.name}`} d={d} />
        <Panel title={t("referees.detail.candidates.title")}>
          {!d.candidates.length ? (
            <EmptyState compact title={t("referees.detail.candidates.empty")} />
          ) : (
            <TableShell>
              <THead>
                <TH>{t("referees.queue.headers.pair")}</TH>
                <TH>{t("referees.queue.headers.reason")}</TH>
                <TH>{t("referees.queue.headers.decision")}</TH>
              </THead>
              <tbody>
                {d.candidates.map((c) => (
                  <TRow key={c.id}>
                    <TD className="text-sm">
                      <RefereeLink id={c.other.id} name={c.other.name} />
                      <div className="text-caption text-subtle-foreground">
                        {t("referees.queue.matches", { n: c.other.matches })}
                      </div>
                    </TD>
                    <TD className="text-xs">{reasonLabel(c.reason)}</TD>
                    <TD className="text-xs">
                      <PairDecision
                        a={{ id: r.id, name: r.name, country: r.country, matches: r.matches }}
                        b={c.other}
                        status={c.status}
                      />
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>
      </div>
      <Aliases key={`${r.id}:${d.aliases.length}`} d={d} />
      <Panel title={t("referees.detail.matches.title")}>
        {!d.recent_matches.length ? (
          <EmptyState compact title={t("referees.detail.matches.empty")} />
        ) : (
          <TableShell>
            <THead>
              <TH>{t("referees.detail.matches.headers.date")}</TH>
              <TH>{t("referees.detail.matches.headers.match")}</TH>
              <TH>{t("referees.detail.matches.headers.competition")}</TH>
              <TH>{t("referees.detail.matches.headers.spelling")}</TH>
            </THead>
            <tbody>
              {d.recent_matches.map((m) => (
                <TRow key={m.fixture_id}>
                  <TD className="text-xs text-muted-foreground">{utcDate(m.kickoff_at)}</TD>
                  <TD className="text-sm">
                    <Link
                      to="/matches/$fixtureId"
                      params={{ fixtureId: String(m.fixture_id) }}
                      className="hover:text-primary"
                    >
                      {m.home} – {m.away}
                    </Link>
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {m.competition} {m.season}
                  </TD>
                  <TD className="text-xs">{m.spelling}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </Panel>
      <Events events={d.events} />
    </div>
  );
}
