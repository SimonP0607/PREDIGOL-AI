/**
 * The price clock (plan F1) in the Admin Console, under "Mercados": how much of what the provider quoted before
 * kick-off has been structured from the RAW /odds bodies, what still waits, what the table weighs and what went
 * wrong. Reading only - it asks the provider nothing and changes no decision. Counts the server could not make in the
 * time it allows itself arrive as null and are shown as such, never as zero.
 */
import { t, translateOr } from "@/lib/i18n";
import { localFixed, localInt } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { TD, TH, THead, TRow, TableShell, TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { IntelPriceClock } from "@/lib/api/v1/types_intel";
import { Note, Stat, StatGrid, SubTitle } from "./AiBits";
import { bogotaDateTime, toNum } from "./aiModel";
import { durationMs } from "./format";

const DASH = "—";

const LEDGER_TONE: Record<string, BadgeTone> = {
  ok: "positive",
  empty: "neutral",
  after_kickoff: "neutral",
  no_fixture: "warning",
  error: "negative",
};

const MARKET_TONE: Record<string, BadgeTone> = {
  ACTIVE: "positive",
  RESEARCH: "info",
};

/** A count: a whole number, or a dash when the server could not make it. */
function count(v: number | null | undefined): string {
  return v === null || v === undefined ? DASH : localInt(v);
}

function when(iso: string | null | undefined): string {
  return iso ? bogotaDateTime(iso) : DASH;
}

function span(from: string | null | undefined, to: string | null | undefined): string {
  return from || to ? `${when(from)} → ${when(to)}` : DASH;
}

function runMs(started: string, finished: string | null): number | null {
  if (!finished) return null;
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

/** The whole panel from data already in hand (so it renders, and is tested, without a network). */
export function PriceClockBody({ d }: { d: IntelPriceClock }) {
  const structured = d.ledger.some((r) => r.status === "ok");
  const countsMissing = d.bets.length > 0 && d.bets.every((b) => b.quotes === null);
  const gigabytes = toNum(d.quotes.gigabytes);
  return (
    <div className="space-y-4" data-testid="intel-price-clock">
      <Note>{t("intel.markets.clock.explain")}</Note>
      {!structured ? <Note>{t("intel.markets.clock.empty")}</Note> : null}
      <StatGrid className="lg:grid-cols-4" testId="intel-price-clock-stats">
        <Stat
          label={t("intel.markets.clock.rawBodies")}
          value={count(d.raw.payloads)}
          hint={span(d.raw.first, d.raw.last)}
        />
        <Stat
          label={t("intel.markets.clock.pending")}
          value={d.backlog === 0 ? t("intel.markets.clock.upToDate") : count(d.backlog)}
          tone={d.backlog === 0 ? "positive" : "warning"}
          hint={t("intel.markets.clock.pendingHint")}
        />
        <Stat
          label={t("intel.markets.clock.quotes")}
          value={count(d.quotes.quotes)}
          hint={span(d.quotes.first, d.quotes.last)}
        />
        <Stat label={t("intel.markets.clock.fixtures")} value={count(d.quotes.fixtures)} />
        <Stat
          label={t("intel.markets.clock.size")}
          value={gigabytes === null ? DASH : `${localFixed(gigabytes, 2)} GB`}
        />
        <Stat label={t("intel.markets.clock.extractor")} value={d.extractor} />
      </StatGrid>

      {d.ledger.length ? (
        <div className="space-y-2">
          <SubTitle>{t("intel.markets.clock.ledger")}</SubTitle>
          <Note>{t("intel.markets.clock.ledgerHelp")}</Note>
          <TableShell>
            <THead>
              <TH>{t("intel.cols.state")}</TH>
              <TH>{t("intel.markets.clock.version")}</TH>
              <TH align="right">{t("intel.markets.clock.bodies")}</TH>
              <TH align="right">{t("intel.markets.clock.quotes")}</TH>
              <TH align="right">{t("intel.markets.clock.refused")}</TH>
              <TH>{t("intel.markets.clock.last")}</TH>
            </THead>
            <tbody>
              {d.ledger.map((r) => (
                <TRow key={`${r.status}-${r.version}`}>
                  <TD>
                    <StatusBadge tone={LEDGER_TONE[r.status] ?? "neutral"} dot={false}>
                      {translateOr(`intel.markets.clock.status.${r.status}`, r.status)}
                    </StatusBadge>
                  </TD>
                  <TD className="font-mono text-caption">{r.version}</TD>
                  <TD align="right">{count(r.payloads)}</TD>
                  <TD align="right">{count(r.quotes)}</TD>
                  <TD align="right">{count(r.refused)}</TD>
                  <TD className="text-xs">{when(r.last)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </div>
      ) : null}

      <div className="space-y-2">
        <SubTitle>{t("intel.markets.clock.families")}</SubTitle>
        <Note>{t("intel.markets.clock.familiesHelp")}</Note>
        {countsMissing ? <Note>{t("intel.markets.clock.countsLate")}</Note> : null}
        <TableShell>
          <THead>
            <TH>{t("intel.markets.clock.family")}</TH>
            <TH align="right">{t("intel.markets.clock.bets")}</TH>
            <TH align="right">{t("intel.markets.clock.extracted")}</TH>
            <TH align="right">{t("intel.markets.clock.quotes")}</TH>
          </THead>
          <tbody>
            {d.families.map((f) => (
              <TRow key={f.key}>
                <TD>{translateOr(`intel.markets.clock.familyName.${f.key}`, f.label)}</TD>
                <TD align="right">{count(f.bets)}</TD>
                <TD align="right">{count(f.extracted)}</TD>
                <TD align="right">{count(f.quotes)}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      </div>

      {d.bets.length ? (
        <div className="space-y-2">
          <SubTitle>{t("intel.markets.clock.structured")}</SubTitle>
          <TableShell>
            <THead>
              <TH>#</TH>
              <TH>{t("intel.markets.market")}</TH>
              <TH>{t("intel.markets.clock.family")}</TH>
              <TH>{t("intel.markets.clock.period")}</TH>
              <TH>{t("intel.markets.clock.subject")}</TH>
              <TH>{t("intel.markets.clock.reading")}</TH>
              <TH>{t("intel.cols.state")}</TH>
              <TH align="right">{t("intel.markets.clock.quotes")}</TH>
              <TH>{t("intel.markets.clock.last")}</TH>
            </THead>
            <tbody>
              {d.bets.map((b) => (
                <TRow key={b.bet_id}>
                  <TD>{b.bet_id}</TD>
                  <TD className="max-w-[14rem] break-words">{b.name}</TD>
                  <TD>{translateOr(`intel.markets.clock.familyName.${b.family}`, b.family)}</TD>
                  <TD>{translateOr(`intel.markets.clock.periodName.${b.period}`, b.period)}</TD>
                  <TD>{translateOr(`intel.markets.clock.subjectName.${b.subject}`, b.subject)}</TD>
                  <TD className="font-mono text-caption">{b.schema}</TD>
                  <TD>
                    <StatusBadge tone={MARKET_TONE[b.status] ?? "neutral"} dot={false}>
                      {translateOr(`intel.markets.status.${b.status}`, b.status)}
                    </StatusBadge>
                  </TD>
                  <TD align="right">{count(b.quotes)}</TD>
                  <TD className="text-xs">{when(b.last)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </div>
      ) : null}

      {d.issues.length ? (
        <div className="space-y-2" data-testid="intel-price-clock-issues">
          <SubTitle>{t("intel.markets.clock.issues")}</SubTitle>
          <Note>{t("intel.markets.clock.issuesHelp")}</Note>
          <TableShell>
            <THead>
              <TH>{t("intel.markets.clock.body")}</TH>
              <TH align="right">{t("intel.markets.clock.providerFixture")}</TH>
              <TH>{t("intel.cols.state")}</TH>
              <TH align="right">{t("intel.markets.clock.refused")}</TH>
              <TH>{t("intel.markets.clock.detail")}</TH>
              <TH>{t("intel.markets.clock.last")}</TH>
            </THead>
            <tbody>
              {d.issues.map((i) => (
                <TRow key={`${i.payload}-${i.extracted_at}`}>
                  <TD className="font-mono text-caption">{i.payload}</TD>
                  <TD align="right">{i.provider_fixture_id ?? DASH}</TD>
                  <TD>
                    <StatusBadge tone={LEDGER_TONE[i.status] ?? "neutral"} dot={false}>
                      {translateOr(`intel.markets.clock.status.${i.status}`, i.status)}
                    </StatusBadge>
                  </TD>
                  <TD align="right">{count(i.quotes_refused)}</TD>
                  <TD className="max-w-[24rem] break-words text-xs">{i.detail ?? DASH}</TD>
                  <TD className="text-xs">{when(i.extracted_at)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </div>
      ) : null}

      {d.unclassified.length ? (
        <div className="space-y-2" data-testid="intel-price-clock-unclassified">
          <SubTitle>{t("intel.markets.clock.unclassified")}</SubTitle>
          <Note>{t("intel.markets.clock.unclassifiedHelp")}</Note>
          <ul className="space-y-0.5 text-xs">
            {d.unclassified.map((u) => (
              <li key={u.bet_id}>
                <span className="numeric">{u.bet_id}</span> · {u.name}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {d.runs.length ? (
        <div className="space-y-2">
          <SubTitle>{t("intel.markets.clock.runs")}</SubTitle>
          <TableShell>
            <THead>
              <TH>{t("intel.costs.started")}</TH>
              <TH>{t("intel.costs.status")}</TH>
              <TH align="right">{t("intel.costs.duration")}</TH>
              <TH align="right">{t("intel.markets.clock.rows")}</TH>
              <TH align="right">{t("intel.costs.errors")}</TH>
              <TH>{t("intel.markets.clock.detail")}</TH>
            </THead>
            <tbody>
              {d.runs.map((r) => (
                <TRow key={r.id}>
                  <TD className="text-xs">{when(r.started_at)}</TD>
                  <TD>{r.status}</TD>
                  <TD align="right">{durationMs(runMs(r.started_at, r.finished_at))}</TD>
                  <TD align="right">{count(r.rows_written)}</TD>
                  <TD align="right">{count(r.errors)}</TD>
                  <TD className="max-w-[24rem] break-words text-xs">
                    {r.last_error ?? r.notes ?? DASH}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </div>
      ) : null}
    </div>
  );
}

export function PriceClockPanel() {
  const q = useLiveQuery(live.intelPriceClock);
  const d = q.data?.data;
  return (
    <Panel title={t("intel.markets.clock.title")} subtitle={t("intel.markets.clock.subtitle")}>
      {d ? (
        <PriceClockBody d={d} />
      ) : q.error ? (
        <ApiErrorNotice error={q.error} />
      ) : q.isLoading ? (
        <TableSkeleton rows={4} cols={4} />
      ) : null}
    </Panel>
  );
}
