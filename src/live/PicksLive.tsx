/**
 * Picks Center, live. The lifecycle is shown as it is - most prices are
 * rejected, nothing qualifies until a model has beaten the market, and
 * publishing does not exist - and every pick opens onto its lineage.
 */
import { t, translateOr } from "@/lib/i18n";
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, MetricCard, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { SegmentedTabs } from "@/components/system/Filters";
import { MetricLabel } from "@/components/system/InfoTip";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, Nullable, SectionView } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { PickRow, PickStatus } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { dec, decPct, shortHash, utcDateTime } from "./format";
import { localFixed } from "@/lib/i18n/format";
import { marketShort, selectionLabel } from "@/product/shared/markets";
import { rejectionReason } from "./labels";

const statusTone: Record<PickStatus, BadgeTone> = {
  shadow: "neutral",
  qualified: "brand",
  published: "positive",
  settled: "info",
};

const resultTone: Record<string, BadgeTone> = {
  win: "positive",
  half_win: "positive",
  loss: "negative",
  half_loss: "negative",
  push: "neutral",
  void: "neutral",
  pending: "warning",
};

function signedPct(value: string | null | undefined, digits = 1): string | null {
  if (value === null || value === undefined) return null;
  const n = Number(value) * 100;
  if (!Number.isFinite(n)) return null;
  return `${n > 0 ? "+" : n < 0 ? "−" : "±"}${localFixed(Math.abs(n), digits)}%`;
}

const tabs = ["Picks", "Candidates"] as const;
type Tab = (typeof tabs)[number];

export function PicksLive() {
  const q = useLiveQuery(live.picks);
  const d = q.data?.data;
  const [tab, setTab] = useState<Tab>("Picks");
  const [open, setOpen] = useState<number | null>(null);
  const lc = d?.lifecycle;
  const stages: Array<[string, string, number | null, string]> = [
    [
      "candidates",
      t("ops.picks.lifecycle.candidates.label"),
      lc ? lc.candidates : null,
      t("ops.picks.lifecycle.candidates.hint"),
    ],
    [
      "rejected",
      t("ops.picks.lifecycle.rejected.label"),
      lc ? lc.rejected : null,
      t("ops.picks.lifecycle.rejected.hint"),
    ],
    [
      "shadow",
      t("ops.picks.lifecycle.shadow.label"),
      lc ? lc.shadow : null,
      t("ops.picks.lifecycle.shadow.hint"),
    ],
    [
      "qualified",
      t("ops.picks.lifecycle.qualified.label"),
      lc ? lc.qualified : null,
      t("ops.picks.lifecycle.qualified.hint"),
    ],
    [
      "published",
      t("ops.picks.lifecycle.published.label"),
      lc ? lc.published : null,
      t("ops.picks.lifecycle.published.hint"),
    ],
    [
      "settled",
      t("ops.picks.lifecycle.settled.label"),
      lc ? lc.settled : null,
      t("ops.picks.lifecycle.settled.hint"),
    ],
  ];
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.picks.title")}
        description={t("admin.pages.picks.description")}
      />
      <WarningBanner>{t("ops.picks.banner")}</WarningBanner>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {stages.map(([stage, label, value, hint]) => (
          <MetricCard
            key={stage}
            label={label}
            value={value === null ? null : int(value)}
            hint={hint}
            tone={stage === "published" ? "muted" : "default"}
          />
        ))}
      </div>
      {d ? (
        <Panel title={t("ops.picks.rule.title")} subtitle={t("ops.picks.rule.subtitle")}>
          <div className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
            <KeyValue
              label={t("ops.picks.rule.version")}
              value={String(d.rule["version"] ?? "—")}
            />
            <KeyValue
              label={t("ops.picks.rule.markets")}
              value={(d.rule["markets"] as string[] | undefined)?.join(", ") ?? "—"}
            />
            <KeyValue
              label={t("ops.picks.rule.oddsRange")}
              value={(d.rule["odds"] as string[] | undefined)?.join(" – ") ?? "—"}
            />
            <KeyValue
              label={t("ops.picks.rule.minEv")}
              value={signedPct(String(d.rule["min_ev"]), 0) ?? "—"}
            />
            <KeyValue
              label={t("ops.picks.rule.minEdge")}
              value={`${localFixed(Number(d.rule["min_probability_edge"]) * 100, 0)} pp`}
            />
            <KeyValue label="Stake" value={t("ops.picks.rule.stakeValue")} />
          </div>
          {Object.keys(d.rejection_reasons).length ? (
            <div className="mt-3">
              <div className="text-label text-subtle-foreground">
                {t("ops.picks.rule.rejections")}
              </div>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {Object.entries(d.rejection_reasons).map(([why, n]) => (
                  <li key={why} className="flex justify-between gap-4">
                    <span>{rejectionReason(why)}</span>
                    <span className="numeric">{int(n)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Panel>
      ) : null}
      <SegmentedTabs
        label={t("ops.picks.tabs.label")}
        tabs={tabs}
        value={tab}
        onChange={setTab}
        format={(v) => (v === "Picks" ? t("ops.picks.tabs.picks") : t("ops.picks.tabs.candidates"))}
      />
      {tab === "Picks" ? (
        <Panel
          title={t("ops.picks.shadow.title")}
          subtitle={t("ops.picks.shadow.subtitle")}
          bodyClassName=""
        >
          {!d ? (
            <TableSkeleton rows={3} cols={9} />
          ) : (
            <SectionView section={d.picks}>
              {(rows) => (
                <TableShell>
                  <THead>
                    <TH>{t("ops.picks.headers.fixture")}</TH>
                    <TH>{t("ops.picks.headers.selection")}</TH>
                    <TH>{t("ops.picks.headers.model")}</TH>
                    <TH align="right">{t("ops.picks.headers.odds")}</TH>
                    <TH align="right">
                      <MetricLabel term="modelProbability">
                        {t("ops.picks.headers.modelP")}
                      </MetricLabel>
                    </TH>
                    <TH align="right">
                      <MetricLabel term="marketProbability">
                        {t("ops.picks.headers.marketP")}
                      </MetricLabel>
                    </TH>
                    <TH align="right">
                      <MetricLabel term="edge">{t("ops.picks.headers.edge")}</MetricLabel>
                    </TH>
                    <TH align="right">
                      <MetricLabel term="ev">{t("ops.picks.headers.ev")}</MetricLabel>
                    </TH>
                    <TH>{t("ops.picks.headers.status")}</TH>
                    <TH>{t("ops.picks.headers.result")}</TH>
                  </THead>
                  <tbody>
                    {rows.flatMap((p) => [
                      <TRow
                        key={p.id}
                        onClick={() => setOpen(open === p.id ? null : p.id)}
                        selected={open === p.id}
                      >
                        <TD>
                          <Link
                            to="/matches/$fixtureId"
                            params={{ fixtureId: String(p.fixture_id) }}
                            className="text-sm hover:text-primary"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {p.fixture}
                          </Link>
                          <div className="text-caption text-subtle-foreground">
                            {p.competition} · {utcDateTime(p.kickoff_at)}
                          </div>
                        </TD>
                        <TD className="text-sm">
                          {marketShort(p.market_key)} · {selectionLabel(p)}
                        </TD>
                        <TD className="text-xs text-muted-foreground">{p.model}</TD>
                        <TD align="right">
                          <Numeric>{dec(p.market_odds)}</Numeric>
                          <div className="text-caption text-subtle-foreground">{p.bookmaker}</div>
                        </TD>
                        <TD align="right">
                          <Numeric>{decPct(p.p_model)}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric muted>{decPct(p.p_market_fair)}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric>{signedPct(p.probability_edge)}</Numeric>
                        </TD>
                        <TD align="right">
                          <Numeric>{signedPct(p.ev)}</Numeric>
                        </TD>
                        <TD>
                          <StatusBadge tone={statusTone[p.status]}>
                            {translateOr(`admin.status.pick.${p.status}`, p.status)}
                          </StatusBadge>
                        </TD>
                        <TD>
                          <StatusBadge tone={resultTone[p.result_status] ?? "neutral"}>
                            {translateOr(
                              `admin.status.result.${p.result_status}`,
                              p.result_status.replace("_", " "),
                            )}
                          </StatusBadge>
                        </TD>
                      </TRow>,
                      open === p.id ? (
                        <tr key={`${p.id}-detail`} className="border-b border-border">
                          <td colSpan={10} className="bg-elevated/40 px-4 py-3">
                            <PickLineage p={p} />
                          </td>
                        </tr>
                      ) : null,
                    ])}
                  </tbody>
                </TableShell>
              )}
            </SectionView>
          )}
        </Panel>
      ) : (
        <Panel
          title={t("ops.picks.candidates.title")}
          subtitle={t("ops.picks.candidates.subtitle")}
          bodyClassName=""
        >
          {!d ? (
            <TableSkeleton rows={3} cols={8} />
          ) : (
            <SectionView section={d.recent_candidates}>
              {(rows) => (
                <TableShell>
                  <THead>
                    <TH>{t("ops.picks.headers.evaluated")}</TH>
                    <TH>{t("ops.picks.headers.fixture")}</TH>
                    <TH>{t("ops.picks.headers.selection")}</TH>
                    <TH>{t("ops.picks.headers.model")}</TH>
                    <TH align="right">{t("ops.picks.headers.odds")}</TH>
                    <TH align="right">{t("ops.picks.headers.ev")}</TH>
                    <TH>{t("ops.picks.headers.decision")}</TH>
                  </THead>
                  <tbody>
                    {rows.map((c) => (
                      <TRow key={c.id}>
                        <TD>
                          <Numeric muted>{utcDateTime(c.evaluated_at)}</Numeric>
                        </TD>
                        <TD className="text-sm">{c.fixture}</TD>
                        <TD className="text-sm">
                          {marketShort(c.market_key)} · {selectionLabel(c)}
                        </TD>
                        <TD className="text-xs text-muted-foreground">{c.model}</TD>
                        <TD align="right">
                          <Nullable
                            value={dec(c.market_odds)}
                            reason={t("ops.picks.candidates.noPrice")}
                            className="numeric"
                          />
                        </TD>
                        <TD align="right">
                          <Nullable
                            value={signedPct(c.ev)}
                            reason={t("ops.picks.candidates.notComputed")}
                            className="numeric"
                          />
                        </TD>
                        <TD>
                          {c.decision === "selected" ? (
                            <StatusBadge tone="brand">selected</StatusBadge>
                          ) : (
                            <div>
                              <StatusBadge tone="neutral">rejected</StatusBadge>
                              <div className="mt-0.5 text-caption text-subtle-foreground">
                                {c.rejection_reason}
                              </div>
                            </div>
                          )}
                        </TD>
                      </TRow>
                    ))}
                  </tbody>
                </TableShell>
              )}
            </SectionView>
          )}
        </Panel>
      )}
    </div>
  );
}

function PickLineage({ p }: { p: PickRow }) {
  const reasons = p.qualification.reasons ?? [];
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div>
        <div className="mb-1 text-label text-subtle-foreground">
          {t("ops.picks.lineage.forecast")}
        </div>
        <KeyValue label={t("ops.picks.lineage.modelVersion")} value={p.model_version} />
        <KeyValue
          label={t("ops.picks.lineage.prediction")}
          value={p.prediction_id ? `#${p.prediction_id}` : "—"}
        />
        <KeyValue label={t("ops.picks.lineage.dataCutoff")} value={utcDateTime(p.data_cutoff_ts)} />
        <KeyValue label={t("ops.picks.lineage.inputHash")} value={shortHash(p.feature_set_hash)} />
        <KeyValue
          label={t("ops.picks.lineage.calibrated")}
          value={p.calibrated ? t("ops.common.yes") : t("ops.picks.lineage.uncalibrated")}
        />
        <KeyValue
          label={t("ops.picks.lineage.interval")}
          value={
            <Nullable
              value={p.p_lo && p.p_hi ? `${decPct(p.p_lo)} – ${decPct(p.p_hi)}` : null}
              reason={t("ops.picks.lineage.noInterval")}
            />
          }
        />
      </div>
      <div>
        <div className="mb-1 text-label text-subtle-foreground">{t("ops.picks.lineage.price")}</div>
        <KeyValue label={t("ops.picks.lineage.bookmaker")} value={p.bookmaker} />
        <KeyValue label={t("ops.picks.lineage.odds")} value={dec(p.market_odds)} />
        <KeyValue label={t("ops.picks.lineage.captured")} value={utcDateTime(p.odds_captured_at)} />
        <KeyValue label="Payload" value={shortHash(p.odds_payload_hash)} />
        <KeyValue
          label={t("ops.picks.lineage.consensus")}
          value={`${p.consensus_method ?? "—"} · ${utcDateTime(p.consensus_as_of)}`}
        />
        <KeyValue label={t("ops.picks.lineage.fairOdds")} value={dec(p.fair_odds)} />
        <KeyValue label={t("ops.picks.lineage.priceEdge")} value={signedPct(p.price_edge) ?? "—"} />
        <KeyValue
          label={t("ops.picks.lineage.evLowerBound")}
          value={signedPct(p.ev_at_lower_bound) ?? "—"}
        />
      </div>
      <div>
        <div className="mb-1 text-label text-subtle-foreground">
          {t("ops.picks.lineage.decision")}
        </div>
        <KeyValue label={t("ops.picks.lineage.rule")} value={p.decision_rule_version} />
        <KeyValue label={t("ops.picks.lineage.code")} value={shortHash(p.code_version)} />
        <KeyValue label="Stake" value={`${dec(p.stake_units)} u · ${p.stake_policy}`} />
        <KeyValue label={t("ops.picks.lineage.kelly")} value={decPct(p.kelly_fraction)} />
        <KeyValue
          label={t("ops.picks.lineage.qualified")}
          value={p.qualification.qualified ? t("ops.common.yes") : t("ops.common.no")}
        />
        {reasons.map((r) => (
          <p key={r} className="text-caption text-muted-foreground">
            · {r}
          </p>
        ))}
        <KeyValue
          label={t("ops.picks.lineage.result")}
          value={`${translateOr(`admin.status.result.${p.result_status}`, p.result_status)}${p.profit_units !== null ? ` · ${dec(p.profit_units, 2)} u` : ""}`}
        />
        <KeyValue label={t("ops.picks.lineage.basis")} value={p.settlement_basis ?? "—"} />
        {p.review_reason ? (
          <p className="text-caption text-warning">
            {t("ops.picks.lineage.needsReview", { reason: p.review_reason })}
          </p>
        ) : null}
        <div className="mt-2 text-label text-subtle-foreground">
          {t("ops.picks.lineage.history")}
        </div>
        <ul className="mt-1 space-y-0.5 text-caption text-muted-foreground">
          {p.events.map((e) => (
            <li key={`${e.at}-${e.to_status}`}>
              <span className="numeric">{utcDateTime(e.at)}</span> · {e.from_status ?? "∅"} →{" "}
              {e.to_status} · {e.reason}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
