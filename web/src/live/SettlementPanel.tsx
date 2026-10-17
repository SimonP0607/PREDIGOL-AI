/**
 * How long each match's bets waited after it ended (first settlement per match), and the
 * matches that ended and still have bets open. The provider gives no instant at which it
 * declared a match over: it lies between the last state seen in play and the first seen ended.
 */
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { Link } from "@tanstack/react-router";
import { MetricCard, Panel } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import { waitText } from "./format";

function when(iso: string | null | undefined): string {
  return iso ? formatDateTime(iso) : "—";
}

export function SettlementPanel() {
  const q = useLiveQuery(live.settlementLatency);
  const d = q.data?.data;
  return (
    <Panel
      title={t("ops.picks.settlement.title")}
      subtitle={t("ops.picks.settlement.subtitle")}
      bodyClassName=""
    >
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {!d ? (
        <TableSkeleton rows={3} cols={7} />
      ) : (
        <div className="space-y-4">
          <div className="grid gap-3 px-4 pt-1 sm:grid-cols-2 xl:grid-cols-5">
            <MetricCard label={t("ops.picks.settlement.matches")} value={String(d.matches)} />
            <MetricCard
              label={t("ops.picks.settlement.median")}
              value={waitText(d.median_seconds)}
            />
            <MetricCard label={t("ops.picks.settlement.mean")} value={waitText(d.mean_seconds)} />
            <MetricCard label={t("ops.picks.settlement.p90")} value={waitText(d.p90_seconds)} />
            <MetricCard
              label={t("ops.picks.settlement.waiting")}
              value={String(d.waiting.length)}
              tone={d.waiting.length ? "default" : "muted"}
            />
          </div>
          {d.waiting.length ? (
            <TableShell>
              <THead>
                <TH>{t("ops.picks.settlement.match")}</TH>
                <TH>{t("ops.picks.settlement.status")}</TH>
                <TH>{t("ops.picks.settlement.ended")}</TH>
                <TH align="right">{t("ops.picks.settlement.open")}</TH>
                <TH>{t("ops.picks.settlement.reason")}</TH>
              </THead>
              <tbody>
                {d.waiting.map((w) => (
                  <TRow key={w.fixture_id}>
                    <TD className="text-sm">
                      <Link
                        to="/matches/$fixtureId"
                        params={{ fixtureId: String(w.fixture_id) }}
                        className="hover:underline"
                      >
                        {w.home} – {w.away}
                      </Link>
                    </TD>
                    <TD>
                      <StatusBadge tone="warning">{w.status_short}</StatusBadge>
                    </TD>
                    <TD>
                      <Numeric muted>{when(w.ended_at)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{w.open_picks + w.open_items}</Numeric>
                    </TD>
                    <TD className="max-w-[24rem] text-xs text-muted-foreground">
                      {w.review_reason ?? t("ops.picks.settlement.noReason")}
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          ) : null}
          {d.rows.length ? (
            <TableShell>
              <THead>
                <TH>{t("ops.picks.settlement.match")}</TH>
                <TH>{t("ops.picks.settlement.lastInPlay")}</TH>
                <TH>{t("ops.picks.settlement.observed")}</TH>
                <TH>{t("ops.picks.settlement.settled")}</TH>
                <TH align="right">{t("ops.picks.settlement.delay")}</TH>
                <TH>{t("ops.picks.settlement.path")}</TH>
                <TH align="right">{t("ops.picks.settlement.records")}</TH>
              </THead>
              <tbody>
                {d.rows.map((r) => (
                  <TRow key={r.fixture_id}>
                    <TD className="text-sm">
                      <Link
                        to="/matches/$fixtureId"
                        params={{ fixtureId: String(r.fixture_id) }}
                        className="hover:underline"
                      >
                        {r.home} – {r.away}
                      </Link>
                      <div className="text-xs text-muted-foreground">
                        {r.competition} · {r.status_short}
                      </div>
                    </TD>
                    <TD>
                      <Numeric muted>{when(r.last_in_play_at)}</Numeric>
                    </TD>
                    <TD>
                      <Numeric muted>{when(r.observed_finished_at)}</Numeric>
                    </TD>
                    <TD>
                      <Numeric muted>{when(r.settled_at)}</Numeric>
                    </TD>
                    <TD align="right">
                      <Numeric>{waitText(r.delay_seconds)}</Numeric>
                    </TD>
                    <TD className="text-xs">{t(`ops.picks.settlement.paths.${r.path}`)}</TD>
                    <TD align="right">
                      <Numeric>
                        {r.picks_settled} / {r.items_settled}
                      </Numeric>
                    </TD>
                  </TRow>
                ))}
              </tbody>
            </TableShell>
          ) : (
            <p className="px-4 pb-4 text-sm text-muted-foreground">
              {t("ops.picks.settlement.empty")}
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
