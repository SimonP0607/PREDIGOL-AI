/**
 * The day's selection funnel for the owner (REVIEW PREDIGOL, B1): the next 24 hours' candidates through every step of
 * the daily set's rule - data, market, model, calibration, value, risk, PrediGol Intelligence, selection - how many
 * pass each, why the others stop, what the next build would add and what nearly made it. Read from the same functions
 * the daily set uses (GET /admin/picks/funnel): the panel cannot describe a rule the set does not apply.
 */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { t, translateOr } from "@/lib/i18n";
import { fmtOdds, fmtPct } from "@/lib/i18n/format";
import { formatKickoff } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/primitives/Panel";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { SegmentedTabs } from "@/components/system/Filters";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { FunnelItem, FunnelStage, SelectionFunnel } from "@/lib/api/v1/types_funnel";
import { marketShort, selectionLabel } from "@/product/shared/markets";

type Source = "evaluation" | "qualified";
const SOURCES: readonly Source[] = ["evaluation", "qualified"];
const DECISION_TONE: Record<string, BadgeTone> = {
  APPROVE: "positive",
  DOWNGRADE: "warning",
  REJECT: "negative",
  ABSTAIN: "neutral",
};

function reasonText(code: string): string {
  return translateOr(`ops.picks.funnel.reason.${code}`, code.replace(/_/g, " "));
}

function StageRow({ s, top }: { s: FunnelStage; top: number }) {
  const width = top > 0 ? Math.max(2, Math.round((s.passed / top) * 100)) : 0;
  const stopped = Object.entries(s.reasons).filter(([, n]) => n > 0);
  return (
    <li className="grid gap-1 py-2 sm:grid-cols-[11rem_minmax(0,1fr)] sm:items-center sm:gap-4">
      <div className="text-sm font-medium">{t(`ops.picks.funnel.stage.${s.key}`)}</div>
      <div className="min-w-0 space-y-1">
        <div className="flex items-center gap-2">
          <span className="relative h-2 flex-1 overflow-hidden rounded-full bg-muted">
            <span
              className={cn(
                "absolute inset-y-0 left-0 rounded-full",
                s.key === "risk" || s.key === "context" ? "bg-gold" : "bg-primary",
              )}
              style={{ width: `${width}%` }}
            />
          </span>
          <span className="numeric w-28 shrink-0 text-right text-xs text-muted-foreground">
            {s.entered} → <span className="font-semibold text-foreground">{s.passed}</span>
          </span>
        </div>
        {stopped.length ? (
          <p className="text-caption text-muted-foreground">
            {stopped.map(([code, n]) => `${reasonText(code)} ${n}`).join(" · ")}
          </p>
        ) : null}
      </div>
    </li>
  );
}

function Evidence({ e }: { e: Record<string, number> }) {
  const entries = Object.entries(e).filter(([, n]) => n > 0);
  if (!entries.length)
    return (
      <span className="text-caption text-subtle-foreground">
        {t("ops.picks.funnel.noEvidence")}
      </span>
    );
  return (
    <span className="text-caption text-muted-foreground">
      {entries
        .map(([status, n]) => `${n} ${translateOr(`ops.picks.funnel.status.${status}`, status)}`)
        .join(" · ")}
    </span>
  );
}

function ItemRow({ x }: { x: FunnelItem }) {
  const label = selectionLabel({
    market_key: x.market_key,
    selection: x.selection,
    line: x.line,
    home: x.home.name,
    away: x.away.name,
  });
  return (
    <li className="grid gap-1 py-2.5 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_auto] sm:items-center sm:gap-4">
      <div className="min-w-0">
        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: String(x.fixture_id) }}
          className="block truncate text-sm font-medium hover:underline"
        >
          {x.home.name} – {x.away.name}
        </Link>
        <div className="truncate text-caption text-muted-foreground">
          {formatKickoff(x.kickoff_at)} · {x.competition.name}
        </div>
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm">
          <span className="text-subtle-foreground">{marketShort(x.market_key)}</span> {label}{" "}
          <span className="numeric font-semibold">@{fmtOdds(x.odds)}</span>
        </div>
        <div className="truncate text-caption text-muted-foreground">
          {fmtPct(x.p_model)} / {fmtPct(x.p_low)} · {t("common.marketProbability")}{" "}
          {fmtPct(x.p_market)}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        {x.stage ? (
          <StatusBadge tone="warning">{reasonText(x.reason ?? x.stage)}</StatusBadge>
        ) : null}
        {x.ai_decision ? (
          <StatusBadge tone={DECISION_TONE[x.ai_decision] ?? "neutral"}>
            {t("ops.picks.funnel.ai")}{" "}
            {translateOr(`records.ai.decision.${x.ai_decision}`, x.ai_decision)}
          </StatusBadge>
        ) : (
          <StatusBadge tone="neutral">{t("ops.picks.funnel.notReviewed")}</StatusBadge>
        )}
        <Evidence e={x.evidence} />
      </div>
    </li>
  );
}

function Body({ d }: { d: SelectionFunnel }) {
  const top = d.stages[0]?.entered ?? 0;
  return (
    <div className="space-y-4">
      <div className="space-y-1 text-caption text-muted-foreground">
        <p>
          {t("ops.picks.funnel.rule", {
            rule: d.rule_version,
            risk: d.risk_version,
            max: fmtOdds(d.max_odds),
            context: d.context_version,
            mode: d.ai_mode,
            enforced: d.ai_enforced ? t("ops.picks.funnel.enforced") : "",
          })}
        </p>
        <p>
          {t("ops.picks.funnel.counts", { candidates: d.candidates, selections: d.selections })}
          {Object.keys(d.in_set).length
            ? ` · ${t("ops.picks.funnel.inSet")}: ${Object.entries(d.in_set)
                .map(([day, n]) => `${day} ${n}`)
                .join(", ")}`
            : ""}
        </p>
      </div>
      <ol className="divide-y divide-border/70" data-testid="funnel-stages">
        {d.stages.map((s) => (
          <StageRow key={s.key} s={s} top={top} />
        ))}
      </ol>
      <div>
        <h3 className="text-sm font-semibold">{t("ops.picks.funnel.chosen")}</h3>
        {d.chosen.length ? (
          <ul className="divide-y divide-border/70" data-testid="funnel-chosen">
            {d.chosen.map((x) => (
              <ItemRow key={`${x.fixture_id}-${x.pick_id}`} x={x} />
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-caption text-muted-foreground">
            {t("ops.picks.funnel.chosenNone")}
          </p>
        )}
      </div>
      <div>
        <h3 className="text-sm font-semibold">{t("ops.picks.funnel.near")}</h3>
        {d.near.length ? (
          <ul className="divide-y divide-border/70" data-testid="funnel-near">
            {d.near.map((x) => (
              <ItemRow key={`${x.fixture_id}-${x.pick_id}-${x.reason}`} x={x} />
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-caption text-muted-foreground">
            {t("ops.picks.funnel.nearNone")}
          </p>
        )}
      </div>
    </div>
  );
}

export function FunnelPanel() {
  const [source, setSource] = useState<Source>("evaluation");
  const q = useLiveQuery(live.selectionFunnel(source));
  const d = q.data?.data;
  return (
    <Panel
      title={t("ops.picks.funnel.title")}
      subtitle={t("ops.picks.funnel.subtitle")}
      actions={
        <SegmentedTabs
          tabs={SOURCES}
          value={source}
          onChange={setSource}
          label={t("ops.picks.funnel.source")}
          format={(s) => t(`ops.picks.funnel.${s}`)}
          className="w-auto"
        />
      }
    >
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {d ? <Body d={d} /> : q.isPending ? <TableSkeleton rows={6} cols={3} /> : null}
    </Panel>
  );
}
