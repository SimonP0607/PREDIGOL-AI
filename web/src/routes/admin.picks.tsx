import { useMemo, useState } from "react";
import { DATA_MODE } from "@/lib/api/mode";
import { DemoRegion } from "@/components/system/DataSources";
import { PicksLive } from "@/live/PicksLive";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import {
  Panel,
  KeyValue,
  MetricCard,
  EmptyState,
  WarningBanner,
} from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { DataStateBadge, PickStatusBadge, StatusBadge } from "@/components/primitives/StatusBadge";
import {
  EdgeIndicator,
  EVIndicator,
  Numeric,
  OddsCell,
  ProbabilityBar,
} from "@/components/primitives/Indicators";
import { MetricLabel } from "@/components/system/InfoTip";
import { SegmentedTabs } from "@/components/system/Filters";
import { queries } from "@/lib/api/resources";
import { dateTimeOf, pct, signedPct, timeOf } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { PickCandidate, PickStatus } from "@/types/domain";

export const Route = createFileRoute("/admin/picks")({
  head: () => ({
    meta: [
      { title: "Picks Center · PrediGol Admin" },
      {
        name: "description",
        content:
          "Decision intelligence over pick candidates: model vs market, edge, expected value, reliability and full traceability. Shadow mode only.",
      },
      { property: "og:title", content: "Picks Center · PrediGol Admin" },
      {
        property: "og:description",
        content: "Candidate research in shadow mode, with edge, expected value and provenance.",
      },
    ],
  }),
  component: RouteComponent,
});

function RouteComponent() {
  if (DATA_MODE === "mock") {
    return (
      <DemoRegion>
        <PicksPage />
      </DemoRegion>
    );
  }
  return <PicksLive />;
}

const tabs = [
  "All",
  "Candidate",
  "Shadow",
  "Qualified",
  "Published",
  "Settled",
  "Rejected",
] as const;
type Tab = (typeof tabs)[number];

const statusOf = (tab: Tab): PickStatus | "all" =>
  tab === "All" ? "all" : (tab.toLowerCase() as PickStatus);

function PicksPage() {
  const picks = useQuery(queries.picks);
  const [tab, setTab] = useState<Tab>("All");
  const filter = statusOf(tab);
  const [selected, setSelected] = useState<string | null>(null);

  const rows = useMemo(
    () => (picks.data ?? []).filter((p) => filter === "all" || p.status === filter),
    [picks.data, filter],
  );
  const detail = (picks.data ?? []).find((p) => p.id === selected) ?? null;

  const counts = (s: PickStatus) => (picks.data ?? []).filter((p) => p.status === s).length;

  return (
    <div className="space-y-5">
      <PageHeader
        breadcrumb={[{ label: "Operations" }, { label: "Picks" }]}
        title="Picks Center"
        description="Candidates produced by shadow-mode models. These are research artefacts for evaluation, not recommendations."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone="brand">Shadow mode</StatusBadge>
          </div>
        }
      />

      <WarningBanner>
        No candidate has been published. Publication requires a validated model, a sufficient sample
        and a near-close price capture — none of which are satisfied yet.
      </WarningBanner>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Candidates" value={String(counts("candidate"))} hint="Awaiting review" />
        <MetricCard label="Shadow" value={String(counts("shadow"))} hint="Tracked, never staked" />
        <MetricCard label="Published" value="0" tone="muted" hint="Blocked by validation gate" />
        <MetricCard label="Settled" value="0" tone="muted" hint="No result history to report" />
      </div>

      <SegmentedTabs
        tabs={tabs}
        value={tab}
        onChange={setTab}
        label="Pick lifecycle state"
        counts={{
          All: picks.data?.length ?? 0,
          Candidate: counts("candidate"),
          Shadow: counts("shadow"),
          Qualified: counts("qualified"),
          Published: counts("published"),
          Settled: counts("settled"),
          Rejected: counts("rejected"),
        }}
      />

      <div className={cn("grid gap-5", detail ? "xl:grid-cols-[1fr_22rem]" : "")}>
        <Panel bodyClassName="">
          {picks.isLoading ? (
            <TableSkeleton rows={6} cols={10} />
          ) : rows.length === 0 ? (
            <EmptyState
              title="No candidates in this state"
              description="Candidate generation only runs for fixtures with a model output and at least one tracked price."
            />
          ) : (
            <TableShell>
              <THead>
                <TH>Fixture</TH>
                <TH>Market</TH>
                <TH>Selection</TH>
                <TH align="right">
                  <MetricLabel term="modelProbability">Model prob</MetricLabel>
                </TH>
                <TH align="right">
                  <MetricLabel term="marketProbability">Market prob</MetricLabel>
                </TH>
                <TH align="right">
                  <MetricLabel term="fairOdds">Fair odds</MetricLabel>
                </TH>
                <TH align="right">
                  <MetricLabel term="bestOdds">Best odds</MetricLabel>
                </TH>
                <TH align="right">
                  <MetricLabel term="edge">Edge</MetricLabel>
                </TH>
                <TH align="right">
                  <MetricLabel term="ev">EV</MetricLabel>
                </TH>
                <TH>
                  <MetricLabel term="reliability">Reliability</MetricLabel>
                </TH>
                <TH>Status</TH>
                <TH align="right">Timestamp</TH>
              </THead>
              <tbody>
                {rows.map((p) => (
                  <TRow key={p.id} onClick={() => setSelected(p.id)} selected={selected === p.id}>
                    <TD>
                      <div className="truncate text-sm">{p.fixtureLabel}</div>
                      <div className="text-caption text-subtle-foreground">{p.competition}</div>
                    </TD>
                    <TD className="whitespace-nowrap text-xs text-muted-foreground">
                      {p.marketLabel}
                    </TD>
                    <TD className="text-sm">{p.selection}</TD>
                    <TD align="right">
                      <Numeric>{pct(p.modelProbability)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric muted>{pct(p.marketProbability)}</Numeric>
                    </TD>
                    <TD align="right">
                      <OddsCell value={p.fairOdds} fair />
                    </TD>
                    <TD align="right">
                      <OddsCell value={p.bestOdds} bookmaker={p.bookmaker} />
                    </TD>
                    <TD align="right">
                      <EdgeIndicator value={p.edge} />
                    </TD>
                    <TD align="right">
                      <EVIndicator value={p.ev} />
                    </TD>
                    <TD>
                      <StatusBadge
                        tone={
                          p.reliability === "high"
                            ? "positive"
                            : p.reliability === "medium"
                              ? "warning"
                              : "neutral"
                        }
                      >
                        {p.reliability}
                      </StatusBadge>
                    </TD>
                    <TD>
                      <PickStatusBadge status={p.status} />
                    </TD>
                    <TD align="right">
                      <Numeric className="text-xs" muted>
                        {timeOf(p.createdAt)}
                      </Numeric>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          )}
        </Panel>

        {detail ? <PickDetail pick={detail} onClose={() => setSelected(null)} /> : null}
      </div>
    </div>
  );
}

function PickDetail({ pick, onClose }: { pick: PickCandidate; onClose: () => void }) {
  return (
    <aside className="surface-panel h-fit xl:sticky xl:top-20">
      <header className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="text-title truncate">{pick.fixtureLabel}</div>
          <div className="text-caption text-subtle-foreground">
            {pick.marketLabel} · {pick.selection}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close detail"
          className="rounded p-1 text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="space-y-4 p-4">
        <div className="flex items-center gap-2">
          <PickStatusBadge status={pick.status} />
          <DataStateBadge state={pick.dataQuality} label={`Data ${pick.dataQuality}`} />
        </div>

        <div>
          <div className="text-label text-subtle-foreground">
            Decision — why this candidate exists
          </div>
          <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">{pick.rationale}</p>
        </div>

        <div className="space-y-1.5">
          <ProbabilityBar value={pick.modelProbability} variant="model" label="Model" />
          <ProbabilityBar value={pick.marketProbability} variant="market" label="Market" />
          <div className="flex justify-between pt-1 text-caption text-subtle-foreground">
            <span>Difference</span>
            <span className="numeric text-foreground">
              {signedPct(pick.modelProbability - pick.marketProbability, 2)}
            </span>
          </div>
        </div>

        <div>
          <div className="text-label text-subtle-foreground">Market</div>
          <KeyValue label="Market baseline" value="Consensus, overround removed" />
          <KeyValue label="Fair odds" value={pick.fairOdds.toFixed(2)} />
          <KeyValue
            label="Available odds"
            value={`${pick.bestOdds.toFixed(2)} · ${pick.bookmaker}`}
          />
          <KeyValue label="Edge" value={signedPct(pick.edge, 2)} />
          <KeyValue label="Expected value" value={signedPct(pick.ev, 2)} />
        </div>

        <div>
          <div className="text-label text-subtle-foreground">Model</div>
          <KeyValue label="Model" value={pick.model} />
          <KeyValue label="Model version" value={pick.modelVersion} />
          <KeyValue label="Reliability" value={pick.reliability} />
          <KeyValue label="Data quality" value={pick.dataQuality} />
        </div>

        <div>
          <div className="text-label text-subtle-foreground">Data provenance</div>
          <KeyValue label="Prediction timestamp" value={dateTimeOf(pick.createdAt)} />
          <KeyValue label="Data cutoff" value={dateTimeOf(pick.dataCutoff)} />
          <KeyValue label="Odds snapshot" value={dateTimeOf(pick.oddsCapturedAt)} />
          <KeyValue label="Pick line value" value="Pending validation" />
        </div>

        <div className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2.5">
          <div className="text-label text-warning">Risk block</div>
          <ul className="mt-1.5 space-y-1.5">
            {pick.risks.map((r) => (
              <li key={r} className="flex items-start gap-2 text-xs text-muted-foreground">
                <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-warning" />
                {r}
              </li>
            ))}
          </ul>
        </div>

        <Link
          to="/matches/$fixtureId"
          params={{ fixtureId: pick.fixtureId }}
          className="block rounded-md border border-border px-3 py-2 text-center text-xs text-muted-foreground hover:border-primary/40 hover:text-primary"
        >
          Open match center
        </Link>
      </div>
    </aside>
  );
}
