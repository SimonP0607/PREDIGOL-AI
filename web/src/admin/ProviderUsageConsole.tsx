/**
 * The owner's console of the provider's requests (plan PM, PM-04-05; UX-175, route BE-076): today with its projection and margin,
 * annex F's figures of a window, the lanes against their ceilings, the days, the endpoints, the competitions and the guards. Built
 * with the console's primitives (`PageHeader`, `MetricCard`, `Panel`, the table, `StatusBadge`, `KeyValue`, `SegmentedTabs`) and no
 * chart. Read-only; shown only with `FBI_USAGE_CONSOLE` on (the «Consumo del proveedor» view of /admin/operation).
 */
import { useState } from "react";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel } from "@/components/primitives/Panel";
import {
  LimitedRows,
  TableShell,
  TableSkeleton,
  TD,
  TH,
  THead,
  TRow,
} from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { FilterBar, SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, StatusNotice } from "@/components/system/LiveState";
import { Banner } from "@/components/ui/banner";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { live } from "@/lib/api/v1/queries";
import type { ProviderUsage } from "@/lib/api/v1/types_provider_usage";
import { int } from "@/lib/format";
import { localFixed } from "@/lib/i18n/format";
import { utcDate, utcDateTime } from "@/live/format";
import { t } from "./usageText";

export const WINDOWS = ["7", "30", "90"] as const;
export type WindowDays = (typeof WINDOWS)[number];

function Figures({ usage }: { usage: ProviderUsage }) {
  const { today, window: w } = usage;
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" data-testid="usage-figures">
      <MetricCard
        label={t("usage.kpi.today")}
        value={int(today.spent)}
        hint={t("usage.kpi.todayHint", { n: int(today.counted) })}
      />
      <MetricCard
        label={t("usage.kpi.projected")}
        value={int(today.projected)}
        tone={today.margin < 0 ? "negative" : today.margin_pct < 25 ? "warning" : "default"}
        hint={t("usage.kpi.projectedHint", {
          margin: int(today.margin),
          pct: localFixed(today.margin_pct, 1),
          budget: int(today.budget),
        })}
      />
      <MetricCard
        label={t("usage.kpi.mean")}
        value={int(Math.round(w.mean))}
        hint={t("usage.kpi.meanHint", { median: int(Math.round(w.median)), days: w.days })}
      />
      <MetricCard
        label={t("usage.kpi.maxNormal")}
        value={int(w.max_normal)}
        hint={t("usage.kpi.maxNormalHint", {
          day: utcDate(w.max_normal_day),
          n: w.exhausted_days,
          max: int(w.max),
        })}
      />
    </div>
  );
}

function Lanes({ usage }: { usage: ProviderUsage }) {
  return (
    <Panel
      title={t("usage.lanes.title")}
      subtitle={`${t("usage.lanes.subtitle", { mode: t(`usage.guards.mode.${usage.guards.lanes_mode}`) })}${
        usage.counted_since
          ? ` ${t("usage.lanes.since", { day: utcDate(usage.counted_since) })}`
          : ""
      }`}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH align="right">{t("usage.lanes.priority")}</TH>
          <TH>{t("usage.lanes.lane")}</TH>
          <TH align="right">{t("usage.lanes.today")}</TH>
          <TH align="right">{t("usage.lanes.ceiling")}</TH>
          <TH>{t("usage.lanes.share")}</TH>
          <TH align="right">{t("usage.lanes.max")}</TH>
        </THead>
        <tbody>
          {usage.lanes.map((l) => (
            <TRow key={l.lane} data-testid="usage-lane">
              <TD align="right" className="numeric text-xs text-muted-foreground">
                {l.priority}
              </TD>
              <TD>
                <span className="text-sm font-semibold">{l.label}</span>{" "}
                {l.vital ? (
                  <StatusBadge tone="brand" dot={false}>
                    {t("usage.lanes.vital")}
                  </StatusBadge>
                ) : null}
              </TD>
              <TD align="right" className="numeric text-sm">
                {int(l.today)}
              </TD>
              <TD align="right" className="numeric text-xs text-muted-foreground">
                {int(l.ceiling)}
              </TD>
              <TD className="min-w-32">
                <div className="flex items-center gap-2">
                  <Progress
                    value={Math.min(100, l.share)}
                    aria-label={t("usage.lanes.progress", {
                      lane: l.label,
                      pct: localFixed(l.share, 1),
                    })}
                    className="h-1.5 bg-foreground/[0.08]"
                  />
                  <span className="numeric w-12 text-right text-xs">
                    {localFixed(l.share, 1)} %
                  </span>
                </div>
              </TD>
              <TD align="right" className="numeric text-xs text-muted-foreground">
                {int(l.max_day)}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

function Days({ usage }: { usage: ProviderUsage }) {
  const rows = [...usage.days].reverse();
  return (
    <Panel title={t("usage.days.title")} subtitle={t("usage.days.subtitle")} bodyClassName="">
      {rows.length === 0 ? (
        <StatusNotice status="empty" reason={t("usage.empty")} />
      ) : (
        <LimitedRows rows={rows} step={14}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("usage.days.day")}</TH>
                <TH align="right">{t("usage.days.spent")}</TH>
                <TH align="right">{t("usage.days.budget")}</TH>
                <TH>{""}</TH>
              </THead>
              <tbody>
                {shown.map((d) => (
                  <TRow key={d.day} data-testid="usage-day">
                    <TD className="numeric text-xs">{utcDate(d.day)}</TD>
                    <TD align="right" className="numeric text-sm">
                      {int(d.spent)}
                    </TD>
                    <TD align="right" className="numeric text-xs text-muted-foreground">
                      {int(d.budget)}
                    </TD>
                    <TD>
                      {d.exhausted ? (
                        <StatusBadge tone="negative">{t("usage.days.exhausted")}</StatusBadge>
                      ) : null}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

function Endpoints({ usage }: { usage: ProviderUsage }) {
  return (
    <Panel
      title={t("usage.endpoints.title")}
      subtitle={t("usage.endpoints.subtitle")}
      bodyClassName=""
    >
      {usage.endpoints.length === 0 ? (
        <StatusNotice status="empty" reason={t("usage.empty")} />
      ) : (
        <LimitedRows rows={usage.endpoints} step={15}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("usage.endpoints.endpoint")}</TH>
                <TH>{t("usage.endpoints.lane")}</TH>
                <TH align="right">{t("usage.endpoints.today")}</TH>
                <TH align="right">{t("usage.endpoints.window")}</TH>
              </THead>
              <tbody>
                {shown.map((e) => (
                  <TRow key={`${e.endpoint}-${e.lane}`} data-testid="usage-endpoint">
                    <TD className="break-all font-mono text-xs">{e.endpoint}</TD>
                    <TD className="text-xs text-muted-foreground">{e.lane}</TD>
                    <TD align="right" className="numeric text-sm">
                      {int(e.today)}
                    </TD>
                    <TD align="right" className="numeric text-xs text-muted-foreground">
                      {int(e.window)}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

function Competitions({ usage }: { usage: ProviderUsage }) {
  return (
    <Panel
      title={t("usage.competitions.title")}
      subtitle={t("usage.competitions.subtitle")}
      bodyClassName=""
    >
      <div className="px-4 pt-3">
        <Banner tone="info" className="text-small">
          {t("usage.competitions.note")}
        </Banner>
      </div>
      {usage.competitions.length === 0 ? (
        <StatusNotice status="empty" reason={t("usage.empty")} />
      ) : (
        <LimitedRows rows={usage.competitions} step={15}>
          {(shown) => (
            <TableShell>
              <THead>
                <TH>{t("usage.competitions.competition")}</TH>
                <TH>{t("usage.competitions.country")}</TH>
                <TH align="right">{t("usage.competitions.responses")}</TH>
              </THead>
              <tbody>
                {shown.map((c) => (
                  <TRow key={c.league_id} data-testid="usage-competition">
                    <TD className="text-sm">
                      {c.name ?? t("usage.competitions.unknown", { id: c.league_id })}
                    </TD>
                    <TD className="text-xs text-muted-foreground">{c.country ?? "—"}</TD>
                    <TD align="right" className="numeric text-sm">
                      {int(c.responses)}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </LimitedRows>
      )}
    </Panel>
  );
}

function Guards({ usage }: { usage: ProviderUsage }) {
  const g = usage.guards;
  const onOff = (b: boolean) => t(b ? "usage.guards.on" : "usage.guards.off");
  return (
    <Panel title={t("usage.guards.title")}>
      <KeyValue label={t("usage.guards.lanes")} value={t(`usage.guards.mode.${g.lanes_mode}`)} />
      <KeyValue label={t("usage.guards.dynamic")} value={onOff(g.dynamic_limits)} />
      <KeyValue label={t("usage.guards.reserve")} value={int(g.emergency_reserve)} />
      <KeyValue label={t("usage.guards.account")} value={onOff(g.account_guard)} />
      <KeyValue label={t("usage.guards.pause")} value={`${int(g.account_pause_seconds)} s`} />
      <KeyValue
        label={t("usage.guards.quiet")}
        value={
          g.quiet_minutes === null
            ? t("usage.guards.quietNone")
            : `${t("usage.guards.quietValue", { n: localFixed(g.quiet_minutes, 0) })} · ${utcDateTime(usage.today.last_request_at)}`
        }
      />
      <p className="mt-2 text-caption text-muted-foreground">{t("usage.guards.note")}</p>
    </Panel>
  );
}

export function ProviderUsageView({ usage }: { usage: ProviderUsage }) {
  return (
    <div className="space-y-4">
      <Figures usage={usage} />
      <div className="grid gap-4 xl:grid-cols-3">
        <div className="xl:col-span-2">
          <Lanes usage={usage} />
        </div>
        <Guards usage={usage} />
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Days usage={usage} />
        <Endpoints usage={usage} />
      </div>
      <Competitions usage={usage} />
    </div>
  );
}

/** The view: a window (7, 30 or 90 days up to a day, today by default) and the answer for it. */
export function ProviderUsageConsole() {
  const [days, setDays] = useState<WindowDays>("30");
  const [until, setUntil] = useState("");
  const q = useLiveQuery(live.adminProviderUsage(until || undefined, Number(days)));
  return (
    <div className="space-y-4" data-testid="usage-console">
      <PageHeader title={t("usage.title")} description={t("usage.description")} />
      <FilterBar>
        <SegmentedTabs
          label={t("usage.window.label")}
          tabs={WINDOWS}
          value={days}
          onChange={setDays}
          format={(n) => t("usage.window.days", { n })}
          className="w-auto"
        />
        <label className="flex flex-col gap-1 text-xs text-muted-foreground" htmlFor="usage-until">
          {t("usage.window.until")}
          <Input
            id="usage-until"
            type="date"
            value={until}
            onChange={(e) => setUntil(e.target.value)}
            className="w-44"
          />
        </label>
        {q.data ? (
          <span className="numeric pb-2 text-caption text-subtle-foreground">
            {t("usage.window.range", {
              since: utcDate(q.data.data.window.since),
              until: utcDate(q.data.data.window.until),
            })}
          </span>
        ) : null}
      </FilterBar>
      {q.isLoading ? (
        <TableSkeleton rows={8} cols={6} />
      ) : q.isError ? (
        <ApiErrorNotice error={q.error} />
      ) : q.data ? (
        <ProviderUsageView usage={q.data.data} />
      ) : null}
    </div>
  );
}
