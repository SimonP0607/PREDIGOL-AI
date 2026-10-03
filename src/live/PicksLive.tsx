/**
 * Picks Center, live. The lifecycle is shown as it is - most prices are
 * rejected, nothing qualifies until a model has beaten the market, and
 * publishing does not exist - and every pick opens onto its lineage.
 */
import { t } from "@/lib/i18n";
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
  return `${n > 0 ? "+" : n < 0 ? "−" : "±"}${Math.abs(n).toFixed(digits)}%`;
}

const tabs = ["Picks", "Candidates"] as const;
type Tab = (typeof tabs)[number];

export function PicksLive() {
  const q = useLiveQuery(live.picks);
  const d = q.data?.data;
  const [tab, setTab] = useState<Tab>("Picks");
  const [open, setOpen] = useState<number | null>(null);
  const lc = d?.lifecycle;
  const stages: Array<[string, number | null, string]> = [
    ["Candidates", lc ? lc.candidates : null, "every captured price evaluated"],
    ["Rejected", lc ? lc.rejected : null, "failed the rule, with the reason"],
    ["Shadow", lc ? lc.shadow : null, "selected, not qualified"],
    ["Qualified", lc ? lc.qualified : null, "model beat the market in its backtest"],
    ["Published", lc ? lc.published : null, "disabled in the schema"],
    ["Settled", lc ? lc.settled : null, "on the 90-minute score"],
  ];
  return (
    <div className="space-y-4">
      <PageHeader
        title={t("admin.pages.picks.title")}
        description={t("admin.pages.picks.description")}
      />
      <WarningBanner>
        Publishing is disabled by a database constraint. Every pick here is shadow research output,
        not advice, and no model has yet qualified: qualification needs the exact model version to
        have beaten the de-vigged market in its own backtest.
      </WarningBanner>
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {stages.map(([label, value, hint]) => (
          <MetricCard
            key={label}
            label={label}
            value={value === null ? null : int(value)}
            hint={hint}
            tone={label === "Published" ? "muted" : "default"}
          />
        ))}
      </div>
      {d ? (
        <Panel title="Decision rule" subtitle="Fixed and versioned before it sees a result">
          <div className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
            <KeyValue label="Version" value={String(d.rule["version"] ?? "—")} />
            <KeyValue
              label="Markets"
              value={(d.rule["markets"] as string[] | undefined)?.join(", ") ?? "—"}
            />
            <KeyValue
              label="Odds range"
              value={(d.rule["odds"] as string[] | undefined)?.join(" – ") ?? "—"}
            />
            <KeyValue label="Minimum EV" value={signedPct(String(d.rule["min_ev"]), 0) ?? "—"} />
            <KeyValue
              label="Minimum probability edge"
              value={`${(Number(d.rule["min_probability_edge"]) * 100).toFixed(0)} pp`}
            />
            <KeyValue label="Stake" value="flat, 1 unit (Kelly reported only)" />
          </div>
          {Object.keys(d.rejection_reasons).length ? (
            <div className="mt-3">
              <div className="text-label text-subtle-foreground">Why prices were rejected</div>
              <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
                {Object.entries(d.rejection_reasons).map(([why, n]) => (
                  <li key={why} className="flex justify-between gap-4">
                    <span>{why}</span>
                    <span className="numeric">{int(n)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Panel>
      ) : null}
      <SegmentedTabs label="Picks view" tabs={tabs} value={tab} onChange={setTab} />
      {tab === "Picks" ? (
        <Panel title="Shadow picks" subtitle="Click a pick for its lineage" bodyClassName="">
          {!d ? (
            <TableSkeleton rows={3} cols={9} />
          ) : (
            <SectionView section={d.picks}>
              {(rows) => (
                <TableShell>
                  <THead>
                    <TH>Fixture</TH>
                    <TH>Selection</TH>
                    <TH>Model</TH>
                    <TH align="right">Odds</TH>
                    <TH align="right">
                      <MetricLabel term="modelProbability">Model p</MetricLabel>
                    </TH>
                    <TH align="right">
                      <MetricLabel term="marketProbability">Market p</MetricLabel>
                    </TH>
                    <TH align="right">
                      <MetricLabel term="edge">Edge</MetricLabel>
                    </TH>
                    <TH align="right">
                      <MetricLabel term="ev">EV</MetricLabel>
                    </TH>
                    <TH>Status</TH>
                    <TH>Result</TH>
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
                          {p.market_key} · {p.selection}
                          {Number(p.line) !== 0 ? ` ${dec(p.line, 2)}` : ""}
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
                          <StatusBadge tone={statusTone[p.status]}>{p.status}</StatusBadge>
                        </TD>
                        <TD>
                          <StatusBadge tone={resultTone[p.result_status] ?? "neutral"}>
                            {p.result_status.replace("_", " ")}
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
          title="Recent candidates"
          subtitle="The last 50 prices evaluated, selected or not"
          bodyClassName=""
        >
          {!d ? (
            <TableSkeleton rows={3} cols={8} />
          ) : (
            <SectionView section={d.recent_candidates}>
              {(rows) => (
                <TableShell>
                  <THead>
                    <TH>Evaluated</TH>
                    <TH>Fixture</TH>
                    <TH>Selection</TH>
                    <TH>Model</TH>
                    <TH align="right">Odds</TH>
                    <TH align="right">EV</TH>
                    <TH>Decision</TH>
                  </THead>
                  <tbody>
                    {rows.map((c) => (
                      <TRow key={c.id}>
                        <TD>
                          <Numeric muted>{utcDateTime(c.evaluated_at)}</Numeric>
                        </TD>
                        <TD className="text-sm">{c.fixture}</TD>
                        <TD className="text-sm">
                          {c.market_key} · {c.selection}
                          {Number(c.line) !== 0 ? ` ${dec(c.line, 2)}` : ""}
                        </TD>
                        <TD className="text-xs text-muted-foreground">{c.model}</TD>
                        <TD align="right">
                          <Nullable
                            value={dec(c.market_odds)}
                            reason="No price."
                            className="numeric"
                          />
                        </TD>
                        <TD align="right">
                          <Nullable
                            value={signedPct(c.ev)}
                            reason="Not computed."
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
        <div className="mb-1 text-label text-subtle-foreground">Forecast</div>
        <KeyValue label="Model version" value={p.model_version} />
        <KeyValue label="Prediction" value={p.prediction_id ? `#${p.prediction_id}` : "—"} />
        <KeyValue label="Data cut-off" value={utcDateTime(p.data_cutoff_ts)} />
        <KeyValue label="Input hash" value={shortHash(p.feature_set_hash)} />
        <KeyValue
          label="Calibrated"
          value={p.calibrated ? "yes" : "no (model's own probability)"}
        />
        <KeyValue
          label="Interval (90%)"
          value={
            <Nullable
              value={p.p_lo && p.p_hi ? `${decPct(p.p_lo)} – ${decPct(p.p_hi)}` : null}
              reason="No interval was computed for this forecast."
            />
          }
        />
      </div>
      <div>
        <div className="mb-1 text-label text-subtle-foreground">Price</div>
        <KeyValue label="Bookmaker" value={p.bookmaker} />
        <KeyValue label="Odds" value={dec(p.market_odds)} />
        <KeyValue label="Captured" value={utcDateTime(p.odds_captured_at)} />
        <KeyValue label="Payload" value={shortHash(p.odds_payload_hash)} />
        <KeyValue
          label="Consensus"
          value={`${p.consensus_method ?? "—"} · ${utcDateTime(p.consensus_as_of)}`}
        />
        <KeyValue label="Model fair odds" value={dec(p.fair_odds)} />
        <KeyValue label="Price edge" value={signedPct(p.price_edge) ?? "—"} />
        <KeyValue label="EV at lower bound" value={signedPct(p.ev_at_lower_bound) ?? "—"} />
      </div>
      <div>
        <div className="mb-1 text-label text-subtle-foreground">Decision & settlement</div>
        <KeyValue label="Rule" value={p.decision_rule_version} />
        <KeyValue label="Code" value={shortHash(p.code_version)} />
        <KeyValue label="Stake" value={`${dec(p.stake_units)} u · ${p.stake_policy}`} />
        <KeyValue label="Kelly (reported only)" value={decPct(p.kelly_fraction)} />
        <KeyValue label="Qualified" value={p.qualification.qualified ? "yes" : "no"} />
        {reasons.map((r) => (
          <p key={r} className="text-caption text-muted-foreground">
            · {r}
          </p>
        ))}
        <KeyValue
          label="Result"
          value={`${p.result_status}${p.profit_units !== null ? ` · ${dec(p.profit_units, 2)} u` : ""}`}
        />
        <KeyValue label="Basis" value={p.settlement_basis ?? "—"} />
        {p.review_reason ? (
          <p className="text-caption text-warning">Needs review: {p.review_reason}</p>
        ) : null}
        <div className="mt-2 text-label text-subtle-foreground">History</div>
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
