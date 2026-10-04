/**
 * Research V2 (GATE F-G): the latest run's roles against the market - CHAMPION, CHALLENGER,
 * RESEARCH, REJECTED - each with its evidence, the forecasts judged prospectively by segment,
 * the shadow picks' returns decomposed, and the runs kept from before the rebuild.
 */
import type { ReactNode } from "react";
import { t, translateOr } from "@/lib/i18n";
import { localFixed, localPct } from "@/lib/i18n/format";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  AuditGroup,
  BlendSummary,
  ProspectiveRow,
  ResearchEntry,
  ResearchRole,
} from "@/lib/api/v1/types_research";
import { utcDateTime } from "./format";
import { baselineLabel } from "./labels";

const ROLE_TONE: Record<ResearchRole, BadgeTone> = {
  CHAMPION: "brand",
  CHALLENGER: "positive",
  RESEARCH: "neutral",
  REJECTED: "negative",
};

export function RoleBadge({ role }: { role: ResearchRole | null }) {
  if (!role) return null;
  return (
    <StatusBadge tone={ROLE_TONE[role]} className="whitespace-nowrap">
      <span data-testid="research-role" data-role={role}>
        {t(`research.v2.role.${role}`)}
      </span>
    </StatusBadge>
  );
}

function signed(v: number, digits = 4): string {
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${localFixed(Math.abs(v), digits)}`;
}

function interval(x: [number, number, number] | null | undefined, digits = 4): string {
  if (!x) return "—";
  return `${signed(x[0], digits)} [${signed(x[1], digits)}, ${signed(x[2], digits)}]`;
}

function weight(b: BlendSummary | null | undefined): string {
  if (!b) return "—";
  return interval([b.w_test, b.w_test_ci[0], b.w_test_ci[1]], 3);
}

function pctSe(mean: number | null, se: number | null): string {
  if (mean === null) return "—";
  return `${localPct(mean, 1, true)}${se === null ? "" : ` ± ${localPct(se, 1)}`}`;
}

function modelName(name: string): string {
  return translateOr(`research.v2.models.${name}`, name);
}

function num(x: unknown, digits = 4): string {
  return typeof x === "number" && Number.isFinite(x) ? localFixed(x, digits) : "—";
}

function ModelsTable({ models }: { models: ResearchEntry[] }) {
  return (
    <TableShell>
      <THead>
        <TH>{t("research.v2.cols.model")}</TH>
        <TH>{t("research.v2.cols.role")}</TH>
        <TH align="right">{t("research.v2.cols.logloss")}</TH>
        <TH>{t("research.v2.cols.vsChampion")}</TH>
        <TH>{t("research.v2.cols.weight")}</TH>
        <TH>{t("research.v2.cols.blend")}</TH>
        <TH>{t("research.v2.cols.weightPreClosing")}</TH>
      </THead>
      <tbody>
        {models.map((m) => {
          const vs = m.metrics["vs_champion"] as { diff?: [number, number, number] } | null;
          const blend = m.metrics["blend"] as BlendSummary | null;
          const pre = m.metrics["blend_pre_closing"] as BlendSummary | null;
          return (
            <TRow key={m.experiment_id}>
              <TD>
                <div className="text-sm font-medium">{modelName(m.model_family)}</div>
                <div
                  className="max-w-[28rem] text-caption text-subtle-foreground"
                  title={m.role_reason ?? ""}
                >
                  {m.role_reason}
                </div>
              </TD>
              <TD>
                <RoleBadge role={m.role} />
              </TD>
              <TD align="right">
                <Numeric>{num(m.metrics["logloss"])}</Numeric>
              </TD>
              <TD>
                <Numeric className="text-xs">{interval(vs?.diff)}</Numeric>
              </TD>
              <TD>
                <Numeric className="text-xs">{weight(blend)}</Numeric>
              </TD>
              <TD>
                <Numeric className="text-xs">{interval(blend?.blend_minus_market)}</Numeric>
              </TD>
              <TD>
                <Numeric className="text-xs">{weight(pre)}</Numeric>
              </TD>
            </TRow>
          );
        })}
      </tbody>
    </TableShell>
  );
}

function MarketsTable({ markets }: { markets: ResearchEntry[] }) {
  const best = markets.find((m) => m.role === "CHAMPION");
  const bestLl =
    typeof best?.metrics["logloss"] === "number" ? (best.metrics["logloss"] as number) : null;
  return (
    <TableShell>
      <THead>
        <TH>{t("research.v2.cols.baseline")}</TH>
        <TH>{t("research.v2.cols.role")}</TH>
        <TH align="right">{t("research.v2.cols.logloss")}</TH>
        <TH align="right">{t("research.v2.cols.vsChampion")}</TH>
      </THead>
      <tbody>
        {markets.map((m) => {
          const ll =
            typeof m.metrics["logloss"] === "number" ? (m.metrics["logloss"] as number) : null;
          const key = m.name.split(":market:")[1] ?? m.name;
          return (
            <TRow key={m.experiment_id}>
              <TD className="text-sm">{baselineLabel(key)}</TD>
              <TD>
                <RoleBadge role={m.role} />
              </TD>
              <TD align="right">
                <Numeric>{num(ll, 5)}</Numeric>
              </TD>
              <TD align="right">
                <Numeric className="text-xs">
                  {ll === null || bestLl === null ? "—" : signed(ll - bestLl, 5)}
                </Numeric>
              </TD>
            </TRow>
          );
        })}
      </tbody>
    </TableShell>
  );
}

function ProspectiveTable({ entries }: { entries: ResearchEntry[] }) {
  const rows = entries.flatMap((e) =>
    ((e.metrics["segments"] as ProspectiveRow[] | undefined) ?? []).filter(
      (r) => r.with_market > 0,
    ),
  );
  if (rows.length === 0) {
    return (
      <p className="px-4 py-3 text-caption text-muted-foreground">
        {t("research.v2.prospective.none")}
      </p>
    );
  }
  rows.sort((a, b) =>
    a.segment === "all" ? -1 : b.segment === "all" ? 1 : a.segment.localeCompare(b.segment),
  );
  return (
    <TableShell>
      <THead>
        <TH>{t("research.v2.cols.segment")}</TH>
        <TH>{t("research.v2.cols.model")}</TH>
        <TH align="right">{t("research.v2.cols.matches")}</TH>
        <TH align="right">{t("research.v2.cols.modelLogloss")}</TH>
        <TH align="right">{t("research.v2.cols.closeLogloss")}</TH>
        <TH>{t("research.v2.cols.difference")}</TH>
        <TH>{t("research.v2.cols.weight")}</TH>
      </THead>
      <tbody>
        {rows.map((r) => (
          <TRow key={`${r.model}:${r.segment}`}>
            <TD className="text-sm">
              {translateOr(`research.v2.segment.${r.segment}`, r.segment)}
            </TD>
            <TD className="text-sm">{modelName(r.model)}</TD>
            <TD align="right">
              <Numeric muted={!r.judged}>{r.with_market}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{num(r.model_logloss)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{num(r.market_logloss)}</Numeric>
            </TD>
            <TD>
              <Numeric className="text-xs" muted={!r.judged}>
                {interval(r.diff)}
              </Numeric>
            </TD>
            <TD>
              <Numeric className="text-xs" muted={!r.judged}>
                {r.blend_w ? interval(r.blend_w, 2) : "—"}
              </Numeric>
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function AuditTable({ audit }: { audit: ResearchEntry }) {
  const byOdds = (audit.metrics["by_odds"] as Record<string, AuditGroup> | undefined) ?? {};
  const overall = audit.metrics["overall"] as AuditGroup | undefined;
  const rows: Array<[string, AuditGroup]> = [
    ...Object.entries(byOdds),
    ...(overall ? ([[t("research.v2.audit.all"), overall]] as Array<[string, AuditGroup]>) : []),
  ];
  return (
    <TableShell>
      <THead>
        <TH>{t("research.v2.audit.odds")}</TH>
        <TH align="right">{t("research.v2.audit.picks")}</TH>
        <TH align="right">{t("research.v2.audit.realised")}</TH>
        <TH align="right">{t("research.v2.audit.claimed")}</TH>
        <TH align="right">{t("research.v2.audit.atClose")}</TH>
        <TH align="right">{t("research.v2.audit.luck")}</TH>
      </THead>
      <tbody>
        {rows.map(([label, g]) => (
          <TRow key={label}>
            <TD className="text-sm">
              <Numeric>{label}</Numeric>
            </TD>
            <TD align="right">
              <Numeric>{g.n}</Numeric>
            </TD>
            <TD align="right">
              <Numeric className="text-xs">{pctSe(g.roi, g.roi_se)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric className="text-xs">
                {g.claimed_ev === null ? "—" : localPct(g.claimed_ev, 1, true)}
              </Numeric>
            </TD>
            <TD align="right">
              <Numeric className="text-xs">{pctSe(g.ev_at_close, g.ev_at_close_se)}</Numeric>
            </TD>
            <TD align="right">
              <Numeric className="text-xs">{pctSe(g.luck, g.luck_se)}</Numeric>
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="border-t border-border">
      <div className="px-4 pb-2 pt-3">
        <h3 className="text-label text-subtle-foreground">{title}</h3>
        {note ? <p className="mt-0.5 text-caption text-muted-foreground">{note}</p> : null}
      </div>
      {children}
    </section>
  );
}

export function ResearchV2Panel() {
  const q = useLiveQuery(live.researchV2);
  const d = q.data?.data;
  return (
    <Panel title={t("research.v2.title")} subtitle={t("research.v2.subtitle")} bodyClassName="">
      <div data-testid="research-v2">
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {!d ? (
          q.isPending ? (
            <TableSkeleton rows={5} cols={6} />
          ) : null
        ) : !d.run ? (
          <p className="px-4 py-3 text-sm text-muted-foreground">{t("research.v2.noRun")}</p>
        ) : (
          <>
            <div className="grid gap-x-8 px-4 py-3 sm:grid-cols-2 xl:grid-cols-3">
              <KeyValue label={t("research.v2.facts.run")} value={d.run} />
              <KeyValue label={t("research.v2.facts.dataAsOf")} value={utcDateTime(d.data_as_of)} />
              <KeyValue label={t("research.v2.facts.features")} value={d.feature_version ?? "—"} />
              <KeyValue
                label={t("research.v2.facts.champion")}
                value={d.champion ? baselineLabel(d.champion) : "—"}
              />
              <KeyValue label={t("research.v2.facts.challengers")} value={String(d.challengers)} />
              <KeyValue
                label={t("research.v2.facts.qualified")}
                value={<span data-testid="research-qualified">{d.qualified_models}</span>}
              />
            </div>
            <div className="px-4 pb-3">
              {d.challengers === 0 ? (
                <WarningBanner>{t("research.v2.noneBeats")}</WarningBanner>
              ) : (
                <WarningBanner tone="info">
                  {t("research.v2.challengersWait", { count: d.challengers })}
                </WarningBanner>
              )}
            </div>
            <Section title={t("research.v2.sections.models")} note={t("research.v2.notes.models")}>
              <ModelsTable models={d.models} />
            </Section>
            <Section
              title={t("research.v2.sections.markets")}
              note={t("research.v2.notes.markets")}
            >
              <MarketsTable markets={d.markets} />
            </Section>
            <Section
              title={t("research.v2.sections.prospective")}
              note={t("research.v2.notes.prospective")}
            >
              <ProspectiveTable entries={d.prospective} />
            </Section>
            {d.audit ? (
              <Section title={t("research.v2.sections.audit")} note={t("research.v2.notes.audit")}>
                <AuditTable audit={d.audit} />
              </Section>
            ) : null}
          </>
        )}
        {d && d.legacy.length > 0 ? (
          <details className="border-t border-border px-4 py-3" data-testid="research-legacy">
            <summary className="cursor-pointer text-xs font-medium text-muted-foreground">
              {t("research.v2.legacy.summary", { count: d.legacy.length })}
            </summary>
            <ul className="mt-2 space-y-1">
              {d.legacy.map((r) => (
                <li
                  key={r.experiment_id}
                  className="flex flex-wrap items-center justify-between gap-2 text-xs"
                >
                  <span className="text-muted-foreground">
                    {r.name} · <StatusBadge tone="neutral">LEGACY_RESEARCH_RUN</StatusBadge>
                  </span>
                  <Numeric className="text-xs">{interval(r.vs_primary)}</Numeric>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>
    </Panel>
  );
}
