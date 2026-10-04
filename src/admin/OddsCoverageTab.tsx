/**
 * BOOKMAKER_COVERAGE_REPORT in the Admin Console: who priced our played matches, what the
 * capture got before kick-off and why it missed the rest, the Colombian operators, and every
 * price source evaluated. Read-only; measured by the API (two-minute cache).
 */
import { useQuery } from "@tanstack/react-query";
import { MetricCard, Panel } from "@/components/primitives/Panel";
import {
  LimitedRows,
  TableShell,
  TableSkeleton,
  TD,
  TH,
  THead,
  TRow,
} from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { live } from "@/lib/api/v1/queries";
import type {
  BookmakerCoverageState,
  CoverageCompetition,
  CoverageState,
  LocalCoverageState,
  MissCause,
  OddsCoverageReport,
  SourceAccess,
} from "@/lib/api/v1/types_truth";
import { t, translateOr } from "@/lib/i18n";
import { localFixed, localInt, localPct } from "@/lib/i18n/format";
import { formatDateTime } from "@/lib/time";
import { EmptyState, ErrorState } from "@/product/shared/States";

const DAYS = 14;
const MISSES: MissCause[] = ["worker_down", "known_too_late", "missed_while_up"];

const COVERAGE_TONE: Record<CoverageState, BadgeTone> = {
  NOT_ASKED: "negative",
  NOT_COVERED: "neutral",
  UNPRICED_BY_PROVIDER: "info",
  THIN: "warning",
  PARTIAL: "warning",
  COVERED: "positive",
};
const BOOK_TONE: Record<BookmakerCoverageState, BadgeTone> = {
  ACTIVE: "positive",
  DORMANT: "warning",
  CATALOGUE_ONLY: "neutral",
};
const LOCAL_TONE: Record<LocalCoverageState, BadgeTone> = {
  PRICED_BY_PROVIDER_BRAND: "positive",
  CATALOGUE_ONLY: "warning",
  NOT_IN_PROVIDER: "neutral",
};
const ACCESS_TONE: Record<SourceAccess, BadgeTone> = {
  ACTIVE: "positive",
  FREE_NEEDS_OWNER: "info",
  PAYMENT_REQUIRED: "warning",
  CLOSED: "neutral",
  REJECTED: "negative",
};

function share(n: number, d: number): string {
  return d ? localPct(n / d, 0) : "—";
}

function books(n: number | null): string {
  return n === null ? "—" : localFixed(n, n % 1 ? 1 : 0);
}

function counts(entries: Record<string, number>, label: (k: string) => string): string {
  const parts = Object.entries(entries)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([k, n]) => `${label(k)} ${localInt(n)}`);
  return parts.length ? parts.join(" · ") : "—";
}

function reason(c: CoverageCompetition): string {
  return t(`truth.coverage.reasons.${c.state}`, {
    fixtures: localInt(c.fixtures),
    asked: localInt(c.asked),
    priced: localInt(c.priced),
    books: books(c.median_bookmakers),
  });
}

export function OddsCoverageTab() {
  const q = useQuery({ ...live.oddsCoverage(DAYS) });
  if (q.isPending) return <TableSkeleton rows={12} cols={8} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const r = q.data?.data;
  if (!r || r.fixtures === 0) return <EmptyState title={q.data?.reason ?? t("common.noData")} />;
  return (
    <div className="space-y-4" data-testid="odds-coverage">
      <p className="text-sm text-muted-foreground">
        {t("truth.coverage.subtitle", {
          days: r.days,
          since: formatDateTime(r.since),
          until: formatDateTime(r.until),
        })}
      </p>
      <Cards r={r} />
      <Critical items={r.critical} />
      <Bookmakers r={r} />
      <Competitions r={r} />
      <div className="grid gap-4 xl:grid-cols-2">
        <Markets r={r} />
        <Countries r={r} />
      </div>
      <Local r={r} />
      <Sources r={r} />
    </div>
  );
}

function Cards({ r }: { r: OddsCoverageReport }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard
        label={t("truth.coverage.cards.provider")}
        value={share(r.priced, r.asked)}
        hint={t("truth.coverage.cards.providerHint", {
          priced: localInt(r.priced),
          asked: localInt(r.asked),
          recovered: localInt(r.recovered),
        })}
      />
      <MetricCard
        label={t("truth.coverage.cards.capture")}
        value={share(r.captured, r.fixtures)}
        hint={t("truth.coverage.cards.captureHint", {
          captured: localInt(r.captured),
          fixtures: localInt(r.fixtures),
        })}
        tone={r.captured < r.fixtures * 0.8 ? "warning" : "default"}
      />
      <MetricCard
        label={t("truth.coverage.cards.misses")}
        value={localInt(MISSES.reduce((s, k) => s + (r.misses[k] ?? 0), 0))}
        hint={t("truth.coverage.cards.missesHint", {
          down: localInt(r.misses.worker_down ?? 0),
          late: localInt(r.misses.known_too_late ?? 0),
          up: localInt(r.misses.missed_while_up ?? 0),
        })}
        tone={(r.misses.missed_while_up ?? 0) > 0 ? "negative" : "default"}
      />
      <MetricCard
        label={t("truth.coverage.cards.downtime")}
        value={`${localInt(Math.round(r.worker_down_hours))} h`}
        hint={t("truth.coverage.cards.downtimeHint")}
        tone={r.worker_down_hours > 0 ? "warning" : "default"}
      />
    </div>
  );
}

function Critical({ items }: { items: string[] }) {
  return (
    <Panel title={t("truth.coverage.critical")} bodyClassName="px-4 py-3">
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="coverage-no-critical">
          {t("truth.coverage.noCritical")}
        </p>
      ) : (
        <ul
          className="list-disc space-y-1 pl-5 text-sm text-negative"
          data-testid="coverage-critical"
        >
          {items.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Bookmakers({ r }: { r: OddsCoverageReport }) {
  return (
    <Panel
      title={t("truth.coverage.bookmakers")}
      subtitle={t("truth.coverage.bookmakersSubtitle")}
      bodyClassName=""
    >
      <LimitedRows rows={r.bookmakers} step={12}>
        {(shown) => (
          <TableShell>
            <THead>
              <TH>{t("truth.coverage.col.bookmaker")}</TH>
              <TH>{t("truth.coverage.col.state")}</TH>
              <TH align="right">{t("truth.coverage.col.matches")}</TH>
              <TH align="right">{t("truth.coverage.col.share")}</TH>
              <TH align="right">{t("truth.coverage.col.competitions")}</TH>
              <TH align="right">{t("truth.coverage.col.countries")}</TH>
              <TH>{t("truth.coverage.col.markets")}</TH>
            </THead>
            <tbody>
              {shown.map((b) => (
                <TRow key={b.provider_bookmaker_id}>
                  <TD>
                    <div className="text-sm">{b.name}</div>
                    <div className="text-caption text-subtle-foreground">
                      #{b.provider_bookmaker_id}
                      {b.name_missing ? ` · ${t("truth.coverage.noName")}` : ""}
                    </div>
                  </TD>
                  <TD>
                    <StatusBadge tone={BOOK_TONE[b.state]}>
                      {t(`truth.coverage.bookStates.${b.state}`)}
                    </StatusBadge>
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(b.fixtures)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {b.fixtures ? localPct(b.share, 0) : "—"}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(b.competitions)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(b.countries)}
                  </TD>
                  <TD className="text-xs text-muted-foreground">{counts(b.markets, (k) => k)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </LimitedRows>
    </Panel>
  );
}

function Competitions({ r }: { r: OddsCoverageReport }) {
  return (
    <Panel
      title={t("truth.coverage.competitions")}
      subtitle={t("truth.coverage.competitionsSubtitle")}
      bodyClassName=""
    >
      <LimitedRows rows={r.competitions} step={25}>
        {(shown) => (
          <TableShell>
            <THead>
              <TH>{t("truth.coverage.col.competition")}</TH>
              <TH>{t("truth.coverage.col.state")}</TH>
              <TH align="right">{t("truth.coverage.col.played")}</TH>
              <TH align="right">{t("truth.coverage.col.asked")}</TH>
              <TH align="right">{t("truth.coverage.col.priced")}</TH>
              <TH align="right">{t("truth.coverage.col.captured")}</TH>
              <TH align="right">{t("truth.coverage.col.recovered")}</TH>
              <TH align="right">{t("truth.coverage.col.books")}</TH>
              <TH>{t("truth.coverage.col.misses")}</TH>
              <TH>{t("truth.coverage.col.upcoming")}</TH>
              <TH>{t("truth.coverage.col.why")}</TH>
            </THead>
            <tbody>
              {shown.map((c) => (
                <TRow key={`${c.competition_id}-${c.season}`}>
                  <TD>
                    <div className="text-sm">{c.competition}</div>
                    <div className="text-caption text-subtle-foreground">
                      {c.country ?? ""} · {c.season}
                    </div>
                  </TD>
                  <TD>
                    <StatusBadge tone={COVERAGE_TONE[c.state]}>
                      {t(`truth.coverage.states.${c.state}`)}
                    </StatusBadge>
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.fixtures)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.asked)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.priced)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.captured)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.recovered)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {books(c.median_bookmakers)}
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {counts(c.misses, (k) => t(`truth.coverage.misses.${k}`))}
                  </TD>
                  <TD className="text-xs text-muted-foreground">
                    {counts(c.upcoming, (k) => t(`truth.state.${k}`))}
                  </TD>
                  <TD className="max-w-xs text-xs text-muted-foreground">{reason(c)}</TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </LimitedRows>
    </Panel>
  );
}

function Markets({ r }: { r: OddsCoverageReport }) {
  return (
    <Panel title={t("truth.coverage.markets")} bodyClassName="">
      <TableShell>
        <THead>
          <TH>{t("truth.coverage.col.market")}</TH>
          <TH align="right">{t("truth.coverage.col.matches")}</TH>
          <TH align="right">{t("truth.coverage.col.share")}</TH>
          <TH align="right">{t("truth.coverage.col.bookmaker")}</TH>
          <TH align="right">{t("truth.coverage.col.books")}</TH>
        </THead>
        <tbody>
          {r.markets.map((m) => (
            <TRow key={m.market_key}>
              <TD className="text-sm">
                {translateOr(`markets.name.${m.market_key}`, m.market_key)}
              </TD>
              <TD align="right" className="numeric text-xs">
                {localInt(m.fixtures)}
              </TD>
              <TD align="right" className="numeric text-xs">
                {localPct(m.share, 0)}
              </TD>
              <TD align="right" className="numeric text-xs">
                {localInt(m.bookmakers)}
              </TD>
              <TD align="right" className="numeric text-xs">
                {books(m.median_bookmakers)}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

function Countries({ r }: { r: OddsCoverageReport }) {
  return (
    <Panel title={t("truth.coverage.countries")} bodyClassName="">
      <LimitedRows rows={r.countries} step={12}>
        {(shown) => (
          <TableShell>
            <THead>
              <TH>{t("truth.coverage.col.country")}</TH>
              <TH align="right">{t("truth.coverage.col.competitions")}</TH>
              <TH align="right">{t("truth.coverage.col.played")}</TH>
              <TH align="right">{t("truth.coverage.col.priced")}</TH>
              <TH align="right">{t("truth.coverage.col.captured")}</TH>
            </THead>
            <tbody>
              {shown.map((c) => (
                <TRow key={c.country}>
                  <TD className="text-sm">{c.country}</TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.competitions)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.fixtures)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.priced)}
                  </TD>
                  <TD align="right" className="numeric text-xs">
                    {localInt(c.captured)}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        )}
      </LimitedRows>
    </Panel>
  );
}

function Local({ r }: { r: OddsCoverageReport }) {
  return (
    <Panel
      title={t("truth.coverage.local")}
      subtitle={t("truth.coverage.localSubtitle", {
        n: r.local.length,
        asOf: r.local_source["as_of"] ?? "—",
      })}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH>{t("truth.coverage.col.brand")}</TH>
          <TH>{t("truth.coverage.col.state")}</TH>
          <TH>{t("truth.coverage.col.providerBook")}</TH>
          <TH align="right">{t("truth.coverage.col.matches")}</TH>
          <TH>{t("truth.coverage.col.note")}</TH>
        </THead>
        <tbody>
          {r.local.map((x) => (
            <TRow key={x.brand}>
              <TD>
                <div className="text-sm">{x.brand}</div>
                <div className="text-caption text-subtle-foreground">{x.domain}</div>
              </TD>
              <TD>
                <StatusBadge tone={LOCAL_TONE[x.state]}>
                  {t(`truth.coverage.localStates.${x.state}`)}
                </StatusBadge>
              </TD>
              <TD className="text-xs">{x.provider_names.join(", ") || "—"}</TD>
              <TD align="right" className="numeric text-xs">
                {localInt(x.priced_fixtures)}
              </TD>
              <TD className="max-w-sm text-xs text-muted-foreground">
                {t(`truth.coverage.localNotes.${x.state}`)}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

function Sources({ r }: { r: OddsCoverageReport }) {
  return (
    <Panel
      title={t("truth.coverage.sources")}
      subtitle={t("truth.coverage.sourcesSubtitle")}
      bodyClassName=""
    >
      <TableShell>
        <THead>
          <TH>{t("truth.coverage.col.source")}</TH>
          <TH>{t("truth.coverage.col.access")}</TH>
          <TH>{t("truth.coverage.col.colombian")}</TH>
          <TH>{t("truth.coverage.col.cost")}</TH>
          <TH>{t("truth.coverage.col.decision")}</TH>
        </THead>
        <tbody>
          {r.sources.map((s) => (
            <TRow key={s.key}>
              <TD>
                <div className="text-sm">{s.name}</div>
                <div className="text-caption text-subtle-foreground">
                  {translateOr(`truth.coverage.kinds.${s.kind}`, s.kind)}
                </div>
              </TD>
              <TD>
                <StatusBadge tone={ACCESS_TONE[s.access]}>
                  {t(`truth.coverage.access.${s.access}`)}
                </StatusBadge>
              </TD>
              <TD className="text-xs">{s.colombian_books.join(", ") || "—"}</TD>
              <TD className="max-w-xs text-xs text-muted-foreground">
                {translateOr(`truth.coverage.sourceText.${s.key}.cost`, s.cost)}
              </TD>
              <TD className="max-w-sm text-xs text-muted-foreground">
                {translateOr(`truth.coverage.sourceText.${s.key}.decision`, s.decision)}
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}
