/**
 * CIERRE DEL DÍA: what a Bogotá day was, as written at 23:59 and revised while a late match settled or
 * its post-mortems arrived (fbi.ai.daily_review). Partidos, picks del día (ganados, perdidos, P&L, valor
 * de línea), selecciones en sombra contra el mercado, lo que decidió la IA y cómo salió, post-mortems,
 * aprendizaje, patrones en observación, hipótesis y experimentos, costos. Read-only: nothing here changes
 * a pick, a model or a rule.
 */
import { t, translateOr } from "@/lib/i18n";
import { fmtSignedPct } from "@/lib/i18n/format";
import { int } from "@/lib/format";
import { formatDateTime } from "@/lib/time";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  DailyReview,
  DailyReviewContent,
  DailyReviewPicks,
} from "@/lib/api/v1/types_ai_layer";
import { DayInput, Note, Stat, StatGrid, SubTitle } from "./AiBits";
import { usd } from "./aiModel";
import { waitText } from "./format";

function units(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  const s = x.toFixed(2).replace(".", ",");
  return `${x > 0 ? "+" : ""}${s} u`;
}

function pct(x: number | null | undefined): string {
  return x === null || x === undefined ? "—" : fmtSignedPct(x);
}

function PicksBlock({ p }: { p: DailyReviewPicks }) {
  if (p.n === 0) return <Note>{t("ai.dailyReview.noPicks")}</Note>;
  return (
    <div className="space-y-2">
      <StatGrid className="lg:grid-cols-6">
        <Stat label={t("ai.dailyReview.picks")} value={int(p.n)} />
        <Stat label={t("ai.dailyReview.won")} value={int(p.won)} tone="positive" />
        <Stat label={t("ai.dailyReview.lost")} value={int(p.lost)} tone="negative" />
        <Stat label={t("ai.dailyReview.pending")} value={int(p.pending)} />
        <Stat label={t("ai.dailyReview.pnl")} value={units(p.pnl_units)} />
        <Stat label={t("ai.dailyReview.lineValue")} value={pct(p.line_value)} />
      </StatGrid>
      <ul className="divide-y divide-border rounded-md border border-border text-xs">
        {p.items.map((i) => (
          <li
            key={i.rank}
            className="flex flex-wrap items-center justify-between gap-2 px-2.5 py-1.5"
          >
            <span className="min-w-0">
              <span className="numeric mr-1.5 text-subtle-foreground">#{i.rank}</span>
              <span className="font-medium">{i.match}</span>
              <span className="text-muted-foreground">
                {" "}
                · {i.market} {i.selection}
                {i.line ? ` ${i.line}` : ""} · {i.odds.toFixed(2)}
                {i.model ? ` · ${i.model}` : ""}
              </span>
            </span>
            <span className="flex items-center gap-1.5">
              {i.ai_last ? (
                <StatusBadge
                  tone={
                    i.ai_last === "APPROVE"
                      ? "positive"
                      : i.ai_last === "REJECT"
                        ? "negative"
                        : "warning"
                  }
                >
                  {t("ai.dailyReview.aiSaid", {
                    decision: translateOr(`records.ai.decision.${i.ai_last}`, i.ai_last),
                  })}
                </StatusBadge>
              ) : null}
              <StatusBadge
                tone={
                  i.status === "WIN" || i.status === "HALF_WIN"
                    ? "positive"
                    : i.status === "PENDING"
                      ? "neutral"
                      : i.status === "LOSS" || i.status === "HALF_LOSS"
                        ? "negative"
                        : "neutral"
                }
              >
                {translateOr(`records.status.${i.status}`, i.status)}
              </StatusBadge>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function AiBlock({ ai }: { ai: Record<string, number> }) {
  const reviewed = ai["reviewed"] ?? 0;
  if (!reviewed) return <Note>{t("ai.dailyReview.noReviews")}</Note>;
  const row = (d: "approve" | "downgrade" | "reject" | "abstain") => (
    <Stat
      key={d}
      label={t(`ai.dailyReview.decision.${d}`)}
      value={int(ai[d] ?? 0)}
      hint={t("ai.dailyReview.wonLost", { won: ai[`${d}_won`] ?? 0, lost: ai[`${d}_lost`] ?? 0 })}
    />
  );
  return (
    <StatGrid className="lg:grid-cols-5">
      <Stat label={t("ai.dailyReview.reviewed")} value={int(reviewed)} />
      {row("approve")}
      {row("downgrade")}
      {row("reject")}
      {row("abstain")}
    </StatGrid>
  );
}

function Body({ r }: { r: DailyReview }) {
  const c: DailyReviewContent = r.content;
  const hyp = c.hypotheses;
  return (
    <div className="space-y-4" data-testid="daily-review">
      <div className="flex flex-wrap items-center gap-2 text-caption text-muted-foreground">
        <StatusBadge tone={r.complete ? "positive" : "warning"}>
          {r.complete
            ? t("ai.dailyReview.complete")
            : t("ai.dailyReview.open", { count: c.pending_fixtures.length })}
        </StatusBadge>
        <span>
          {t("ai.dailyReview.revision", {
            n: r.revision,
            when: formatDateTime(r.built_at),
          })}
        </span>
        {c.waiting_human.length ? (
          <span className="text-warning">
            {t("ai.dailyReview.waitingHuman", { count: c.waiting_human.length })}
          </span>
        ) : null}
      </div>

      <section className="space-y-2">
        <SubTitle>{t("ai.dailyReview.matches")}</SubTitle>
        <StatGrid className="lg:grid-cols-6">
          <Stat label={t("ai.dailyReview.tracked")} value={int(c.matches.tracked)} />
          <Stat label={t("ai.dailyReview.withMarket")} value={int(c.matches.with_market)} />
          <Stat label={t("ai.dailyReview.analysed")} value={int(c.matches.analysed_by_ai)} />
          <Stat label={t("ai.dailyReview.played")} value={int(c.matches.played)} />
          <Stat label={t("ai.dailyReview.notPlayed")} value={int(c.matches.not_played)} />
          <Stat label={t("ai.dailyReview.stillToFinish")} value={int(c.matches.still_to_finish)} />
        </StatGrid>
      </section>

      <section className="space-y-2">
        <SubTitle>{t("ai.dailyReview.dailyPicks")}</SubTitle>
        <Note>{t("ai.dailyReview.dailyPicksHelp")}</Note>
        <PicksBlock p={c.daily_picks} />
      </section>

      <section className="space-y-2">
        <SubTitle>{t("ai.dailyReview.shadow")}</SubTitle>
        <StatGrid className="lg:grid-cols-5">
          <Stat label={t("ai.dailyReview.selections")} value={int(c.shadow.selections)} />
          <Stat label={t("ai.dailyReview.settled")} value={int(c.shadow.settled)} />
          <Stat label={t("ai.dailyReview.won")} value={int(c.shadow.won)} />
          <Stat label={t("ai.dailyReview.pnl")} value={units(c.shadow.pnl_units)} />
          <Stat label={t("ai.dailyReview.roi")} value={pct(c.shadow.roi)} />
        </StatGrid>
        {c.shadow.by_market.length ? (
          <ul className="grid gap-1.5 text-xs sm:grid-cols-2 xl:grid-cols-3">
            {c.shadow.by_market.map((m) => (
              <li key={m.market} className="rounded-md border border-border px-2.5 py-1.5">
                <span className="font-medium">{m.market}</span>{" "}
                <span className="text-muted-foreground">
                  {t("ai.dailyReview.marketLine", {
                    n: m.settled,
                    roi: pct(m.roi),
                    lv: pct(m.line_value_devigged),
                    model: pct(m.p_model),
                    market: pct(m.p_market),
                  })}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="space-y-2">
        <SubTitle>{t("ai.dailyReview.ai")}</SubTitle>
        <AiBlock ai={c.ai} />
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-2">
          <SubTitle>{t("ai.dailyReview.postmortems")}</SubTitle>
          {c.postmortems.n ? (
            <ul className="space-y-1 text-xs">
              {Object.entries(c.postmortems.by_class).map(([k, n]) => (
                <li key={k} className="flex justify-between gap-2">
                  <span>{translateOr(`ai.dailyReview.class.${k}`, k)}</span>
                  <span className="numeric">{n}</span>
                </li>
              ))}
              {Object.entries(c.postmortems.wins_by_quality ?? {}).map(([k, n]) => (
                <li key={k} className="flex justify-between gap-2">
                  <span>{translateOr(`ai.dailyReview.winQuality.${k}`, k)}</span>
                  <span className="numeric">{n}</span>
                </li>
              ))}
              <li className="text-caption text-subtle-foreground">
                {t("ai.dailyReview.postmortemsTotal", { count: c.postmortems.n })}
              </li>
            </ul>
          ) : (
            <Note>{t("ai.dailyReview.noPostmortems")}</Note>
          )}
        </section>
        <section className="space-y-2">
          <SubTitle>{t("ai.dailyReview.learning")}</SubTitle>
          {c.learning.length ? (
            <ul className="list-disc space-y-1 pl-4 text-xs">
              {c.learning.map((n, i) => (
                <li key={i}>{n.title}</li>
              ))}
            </ul>
          ) : (
            <Note>{t("ai.dailyReview.noLearning")}</Note>
          )}
        </section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="space-y-2">
          <SubTitle>{t("ai.dailyReview.patterns")}</SubTitle>
          {c.patterns.length ? (
            <ul className="list-disc space-y-1 pl-4 text-xs">
              {c.patterns.slice(0, 8).map((p, i) => (
                <li key={i}>
                  <span className="text-subtle-foreground">
                    {translateOr(`ai.dailyReview.patternKind.${p.kind}`, p.kind)}:{" "}
                  </span>
                  {p.text ?? "—"}
                </li>
              ))}
            </ul>
          ) : (
            <Note>{t("ai.dailyReview.noPatterns")}</Note>
          )}
        </section>
        <section className="space-y-2">
          <SubTitle>{t("ai.dailyReview.hypotheses")}</SubTitle>
          <StatGrid className="lg:grid-cols-4">
            <Stat label={t("ai.dailyReview.hyp.new")} value={int(hyp.new)} />
            <Stat label={t("ai.dailyReview.hyp.investigating")} value={int(hyp.investigating)} />
            <Stat label={t("ai.dailyReview.hyp.rejected")} value={int(hyp.rejected)} />
            <Stat label={t("ai.dailyReview.hyp.validated")} value={int(hyp.validated)} />
          </StatGrid>
          {hyp.new_titles.length ? (
            <ul className="list-disc space-y-1 pl-4 text-xs">
              {hyp.new_titles.map((h, i) => (
                <li key={i}>{h}</li>
              ))}
            </ul>
          ) : null}
          <Note>
            {t("ai.dailyReview.experiments", {
              started: c.experiments.started,
              finished: c.experiments.finished,
              running: c.experiments.running_at_end,
              waiting: hyp.waiting_owner_at_end,
            })}
          </Note>
        </section>
      </div>

      <section className="space-y-2">
        <SubTitle>{t("ai.dailyReview.costsAndOps")}</SubTitle>
        <StatGrid className="lg:grid-cols-4">
          <Stat label={t("ai.dailyReview.aiCost")} value={usd(c.costs.ai_usd)} />
          <Stat
            label={t("ai.dailyReview.apiRequests")}
            value={int(c.costs.api_football_requests)}
          />
          <Stat
            label={t("ai.dailyReview.settlementMedian")}
            value={waitText(c.settlement.median_seconds)}
            hint={t("ai.dailyReview.settlementMax", { max: waitText(c.settlement.max_seconds) })}
          />
          <Stat label={t("ai.dailyReview.settledMatches")} value={int(c.settlement.matches)} />
        </StatGrid>
      </section>

      {r.revisions.length > 1 ? (
        <section className="space-y-1">
          <SubTitle>{t("ai.dailyReview.revisions")}</SubTitle>
          <ol className="space-y-0.5 text-caption text-muted-foreground">
            {r.revisions.map((v) => (
              <li key={v.revision}>
                {t(`ai.dailyReview.kind.${v.kind}`)} {v.revision} · {formatDateTime(v.built_at)} ·{" "}
                {v.complete
                  ? t("ai.dailyReview.complete")
                  : t("ai.dailyReview.open", { count: v.pending_fixtures.length })}
              </li>
            ))}
          </ol>
        </section>
      ) : null}
    </div>
  );
}

export function DailyReviewPanel({
  day,
  onDay,
  max,
  title,
}: {
  day: string;
  onDay: (d: string) => void;
  max: string;
  title?: string | undefined;
}) {
  const q = useLiveQuery(live.aiDailyReview(day));
  const r = q.data?.data ?? null;
  return (
    <Panel
      title={title ?? t("ai.dailyReview.title")}
      subtitle={t("ai.dailyReview.subtitle")}
      actions={<DayInput value={day} onChange={onDay} max={max} label={t("ai.dailyReview.day")} />}
    >
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={3} cols={6} /> : null}
      {q.isSuccess && !r ? <Note>{q.data.reason ?? t("ai.dailyReview.notClosed")}</Note> : null}
      {r ? <Body r={r} /> : null}
    </Panel>
  );
}
