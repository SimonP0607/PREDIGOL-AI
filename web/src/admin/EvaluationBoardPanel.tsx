/**
 * The owner's private evaluation board on the Performance page (plan PM, PM-12-01 and PM-12-06; IA-153, route
 * `GET /admin/evaluation/board`): for each market, PrediGol's forecast, the market and the provider on the same matches - log loss,
 * Brier split into reliability and resolution, each with its interval and sample - the paired differences with their reading, and
 * the verdict of each competition's own sample. Built with the console's primitives (`Panel`, the table, `StatusBadge`). It renders
 * nothing while `FBI_EVALUATION_BOARD` is off (the route answers 404). Not a proof of an edge; it changes nothing.
 */
import { Panel } from "@/components/primitives/Panel";
import { TableShell, TD, TH, THead, TRow } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { LiveApiError } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  EvalInterval,
  EvalPairedDifference,
  EvalSegmentsSummary,
  EvalWindow,
  EvaluationBoard,
} from "@/lib/api/v1/types_evaluation_board";
import { t } from "@/lib/i18n";
import { localFixed } from "@/lib/i18n/format";

function marketLabel(market: string): string {
  return t(`admin.evaluationBoard.markets.${market}`);
}

function iv(x: EvalInterval): string {
  if (x.value == null) return "—";
  const v = localFixed(x.value, 4);
  return x.low == null || x.high == null
    ? v
    : `${v} [${localFixed(x.low, 4)}; ${localFixed(x.high, 4)}]`;
}

function tone(verdict: string): BadgeTone {
  if (verdict === "modelo_mejor" || verdict === "apta") return "positive";
  if (verdict === "modelo_peor" || verdict === "sin_habilidad") return "negative";
  if (verdict === "insuficiente") return "warning";
  return "neutral";
}

function Pairs({ pairs }: { pairs: EvalPairedDifference[] }) {
  if (!pairs.length) return null;
  return (
    <TableShell>
      <THead>
        <TH>{t("admin.evaluationBoard.pairs")}</TH>
        <TH>{t("admin.evaluationBoard.metric")}</TH>
        <TH align="right">{t("admin.evaluationBoard.n")}</TH>
        <TH align="right">{t("admin.evaluationBoard.difference")}</TH>
        <TH>{t("admin.evaluationBoard.verdictLabel")}</TH>
      </THead>
      <tbody>
        {pairs.map((d) => (
          <TRow key={`${d.b}-${d.metric}`}>
            <TD>
              {t(`admin.evaluationBoard.sources.${d.a}`)} −{" "}
              {t(`admin.evaluationBoard.sources.${d.b}`)}
            </TD>
            <TD>
              {d.metric === "brier"
                ? t("admin.evaluationBoard.brier")
                : t("admin.evaluationBoard.logLoss")}
            </TD>
            <TD align="right">{d.n}</TD>
            <TD align="right">{iv(d)}</TD>
            <TD>
              <StatusBadge tone={tone(d.verdict)}>
                {t(`admin.evaluationBoard.verdicts.${d.verdict}`)}
              </StatusBadge>
            </TD>
          </TRow>
        ))}
      </tbody>
    </TableShell>
  );
}

function WindowTable({ w, title }: { w: EvalWindow; title: string }) {
  return (
    <div className="space-y-2" data-testid="eval-window">
      <div className="text-label text-subtle-foreground">
        {title} · {t("admin.evaluationBoard.matches", { n: w.matches, common: w.common })}
      </div>
      {w.sources.length ? (
        <TableShell>
          <THead>
            <TH>{t("admin.evaluationBoard.source")}</TH>
            <TH align="right">{t("admin.evaluationBoard.n")}</TH>
            <TH align="right">{t("admin.evaluationBoard.logLoss")}</TH>
            <TH align="right">{t("admin.evaluationBoard.brier")}</TH>
            <TH align="right">{t("admin.evaluationBoard.reliability")}</TH>
            <TH align="right">{t("admin.evaluationBoard.resolution")}</TH>
            <TH align="right">{t("admin.evaluationBoard.uncertainty")}</TH>
          </THead>
          <tbody>
            {w.sources.map((s) => (
              <TRow key={s.source}>
                <TD>{t(`admin.evaluationBoard.sources.${s.source}`)}</TD>
                <TD align="right">{s.n}</TD>
                <TD align="right">{iv(s.log_loss)}</TD>
                <TD align="right">{iv(s.brier)}</TD>
                <TD align="right">{iv(s.reliability)}</TD>
                <TD align="right">{iv(s.resolution)}</TD>
                <TD align="right">{localFixed(s.uncertainty, 4)}</TD>
              </TRow>
            ))}
          </tbody>
        </TableShell>
      ) : null}
      <Pairs pairs={w.pairs} />
    </div>
  );
}

function Competitions({ s }: { s: EvalSegmentsSummary }) {
  return (
    <Panel
      title={t("admin.evaluationBoard.competitions")}
      subtitle={t("admin.evaluationBoard.needed", { n: s.needed })}
      actions={
        <StatusBadge tone={s.reproduced ? "positive" : "negative"}>
          {s.reproduced
            ? t("admin.evaluationBoard.reproduced")
            : t("admin.evaluationBoard.notReproduced")}
        </StatusBadge>
      }
    >
      <TableShell>
        <THead>
          <TH>{t("admin.evaluationBoard.competition")}</TH>
          <TH>{t("admin.evaluationBoard.market")}</TH>
          <TH align="right">{t("admin.evaluationBoard.n")}</TH>
          <TH align="right">{t("admin.evaluationBoard.logLoss")}</TH>
          <TH align="right">{t("admin.evaluationBoard.skill")}</TH>
          <TH>{t("admin.evaluationBoard.verdict")}</TH>
        </THead>
        <tbody>
          {s.competitions.map((c) => (
            <TRow key={`${c.competition_id}-${c.market}-${c.model}`}>
              <TD>{c.name ?? `#${c.competition_id}`}</TD>
              <TD>{marketLabel(c.market)}</TD>
              <TD align="right">{c.n}</TD>
              <TD align="right">
                {iv({ value: c.log_loss, low: c.log_loss_low, high: c.log_loss_high })}
              </TD>
              <TD align="right">{iv({ value: c.skill, low: c.skill_low, high: c.skill_high })}</TD>
              <TD>
                <StatusBadge tone={tone(c.verdict)}>
                  {t(`admin.evaluationBoard.verdicts.${c.verdict}`)}
                </StatusBadge>
              </TD>
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

/** The board, given its answer (pure: what the tests render). */
export function EvaluationBoardView({ board }: { board: EvaluationBoard }) {
  const w = board.weekly;
  return (
    <section className="space-y-4" data-testid="evaluation-board">
      <Panel title={t("admin.evaluationBoard.title")} subtitle={t("admin.evaluationBoard.notice")}>
        {w ? (
          <div className="space-y-6">
            {w.markets.map((m) => (
              <div key={m.market} className="space-y-3">
                <h3 className="text-sm font-semibold">{marketLabel(m.market)}</h3>
                <WindowTable
                  w={m.week}
                  title={t("admin.evaluationBoard.week", { from: m.week.from, to: m.week.to })}
                />
                <WindowTable
                  w={m.cumulative}
                  title={t("admin.evaluationBoard.cumulative", { from: m.cumulative.from })}
                />
              </div>
            ))}
          </div>
        ) : (
          <p className="text-caption text-subtle-foreground">{t("admin.evaluationBoard.empty")}</p>
        )}
      </Panel>
      {board.segments ? <Competitions s={board.segments} /> : null}
    </section>
  );
}

/** The panel: nothing while the switch is off (404) or before the answer arrives. */
export function EvaluationBoardPanel() {
  const q = useLiveQuery(live.adminEvaluationBoard);
  if (q.isError && q.error instanceof LiveApiError && q.error.status === 404) return null;
  if (!q.data) return null;
  return <EvaluationBoardView board={q.data.data} />;
}
