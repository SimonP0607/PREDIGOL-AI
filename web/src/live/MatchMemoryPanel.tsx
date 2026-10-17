/**
 * MATCH INTELLIGENCE MEMORY: the matches PrediGol looked at, searchable by team, league, coach, player,
 * market, odds band and model. Each row says what was known BEFORE (the AI's brief, its decisions, the
 * shadow picks) and what came AFTER (the score, how the picks settled, the post-mortems, how the wins were
 * judged). Facts only: the patterns and hypotheses live in Evolución.
 */
import { useState } from "react";
import { keepPreviousData } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { t, translateOr } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { MatchMemory, MemoryFilters } from "@/lib/api/v1/types_ai_layer";
import { Note } from "./AiBits";

const INPUT =
  "h-8 w-full rounded-md border border-border bg-card px-2 text-xs text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";
const MARKETS = ["1X2", "OU", "BTTS", "AH", "DC"];
const BANDS = ["1.20-1.49", "1.50-1.79", "1.80-2.19", "2.20-2.99", "3.00-4.99", "5.00+"];
const MODELS = ["dixon_coles", "poisson", "elo_ologit"];

function Text({
  k,
  value,
  onChange,
}: {
  k: "team" | "competition" | "coach" | "player";
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="space-y-1 text-caption text-subtle-foreground">
      <span className="uppercase tracking-wider">{t(`ai.memory.filters.${k}`)}</span>
      <input className={INPUT} value={value} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}

function Pick({
  k,
  options,
  value,
  onChange,
}: {
  k: "market" | "odds_band" | "model";
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="space-y-1 text-caption text-subtle-foreground">
      <span className="uppercase tracking-wider">{t(`ai.memory.filters.${k}`)}</span>
      <select className={INPUT} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t("ai.memory.any")}</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

function Row({ m }: { m: MatchMemory }) {
  const decisions = Object.entries(m.ai_decisions);
  const classes = Object.entries(m.postmortem_classes);
  const wins = Object.entries(m.win_quality);
  return (
    <li className="space-y-1.5 px-3 py-2.5" data-testid="memory-row">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <span className="min-w-0 text-sm font-medium">
          <Link
            to="/matches/$fixtureId"
            params={{ fixtureId: String(m.fixture_id) }}
            className="hover:text-primary hover:underline"
          >
            {m.home} – {m.away}
          </Link>
          {m.score_home !== null && m.score_away !== null ? (
            <span className="numeric ml-1.5 text-muted-foreground">
              {m.score_home}–{m.score_away}
            </span>
          ) : null}
        </span>
        <span className="text-caption text-muted-foreground">
          {m.competition} · {formatDateTime(m.kickoff_at)}
        </span>
      </div>
      {m.home_coach || m.away_coach ? (
        <p className="text-caption text-subtle-foreground">
          {t("ai.memory.coaches", { home: m.home_coach ?? "—", away: m.away_coach ?? "—" })}
        </p>
      ) : null}
      <div className="grid gap-2 text-xs md:grid-cols-2">
        <div className="rounded-md border border-border px-2 py-1.5">
          <div className="text-caption uppercase tracking-wider text-subtle-foreground">
            {t("ai.memory.before")}
          </div>
          <p className="mt-0.5 text-muted-foreground">
            {m.brief_summary ?? t("ai.memory.noBrief")}
          </p>
          <p className="mt-1 flex flex-wrap gap-1">
            {decisions.map(([d, n]) => (
              <StatusBadge
                key={d}
                tone={d === "APPROVE" ? "positive" : d === "REJECT" ? "negative" : "warning"}
              >
                {translateOr(`records.ai.decision.${d}`, d)} {n}
              </StatusBadge>
            ))}
            <span className="text-caption text-subtle-foreground">
              {t("ai.memory.selections", {
                n: m.selections,
                markets: m.markets.join(", ") || "—",
                models: m.models.join(", ") || "—",
              })}
            </span>
          </p>
        </div>
        <div className="rounded-md border border-border px-2 py-1.5">
          <div className="text-caption uppercase tracking-wider text-subtle-foreground">
            {t("ai.memory.after")}
          </div>
          <p className="mt-0.5 text-muted-foreground">
            {t("ai.memory.settled", {
              won: m.won,
              lost: m.lost,
              pnl:
                m.pnl_units === null
                  ? "—"
                  : `${m.pnl_units > 0 ? "+" : ""}${m.pnl_units.toFixed(2)} u`,
            })}
          </p>
          <p className="mt-1 flex flex-wrap gap-1 text-caption">
            {classes.map(([c, n]) => (
              <StatusBadge key={c} tone="neutral">
                {translateOr(`ai.dailyReview.class.${c}`, c)} {n}
              </StatusBadge>
            ))}
            {wins.map(([q, n]) => (
              <StatusBadge key={q} tone={q === "EARNED" ? "positive" : "warning"}>
                {translateOr(`ai.dailyReview.winQuality.${q}`, q)} {n}
              </StatusBadge>
            ))}
            {m.memory_events ? (
              <span className="text-subtle-foreground">
                {t("ai.memory.events", { count: m.memory_events })}
              </span>
            ) : null}
          </p>
        </div>
      </div>
    </li>
  );
}

export function MatchMemoryPanel() {
  const [draft, setDraft] = useState<Required<Record<keyof MemoryFilters, string>>>({
    team: "",
    competition: "",
    coach: "",
    player: "",
    market: "",
    odds_band: "",
    model: "",
  });
  const [applied, setApplied] = useState<MemoryFilters>({});
  const q = useLiveQuery({ ...live.aiMatchMemory(applied), placeholderData: keepPreviousData });
  const rows = q.data?.data ?? [];
  const set = (k: keyof MemoryFilters) => (v: string) => setDraft((d) => ({ ...d, [k]: v }));
  return (
    <Panel title={t("ai.memory.title")} subtitle={t("ai.memory.subtitle")}>
      <form
        className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(
            Object.fromEntries(
              Object.entries(draft).filter(([, v]) => v.trim() !== ""),
            ) as MemoryFilters,
          );
        }}
      >
        <Text k="team" value={draft.team} onChange={set("team")} />
        <Text k="competition" value={draft.competition} onChange={set("competition")} />
        <Text k="coach" value={draft.coach} onChange={set("coach")} />
        <Text k="player" value={draft.player} onChange={set("player")} />
        <Pick k="market" options={MARKETS} value={draft.market} onChange={set("market")} />
        <Pick k="odds_band" options={BANDS} value={draft.odds_band} onChange={set("odds_band")} />
        <Pick k="model" options={MODELS} value={draft.model} onChange={set("model")} />
        <div className="flex items-end">
          <button
            type="submit"
            className="h-8 w-full rounded-md border border-primary/50 bg-primary/10 px-3 text-xs font-medium text-primary hover:bg-primary/20"
          >
            {t("ai.memory.search")}
          </button>
        </div>
      </form>
      <div className="mt-3">
        {q.isError ? <ApiErrorNotice error={q.error} /> : null}
        {q.isLoading ? <TableSkeleton rows={3} cols={4} /> : null}
        {q.isSuccess && rows.length === 0 ? <Note>{t("ai.memory.empty")}</Note> : null}
        {rows.length ? (
          <ul className="divide-y divide-border rounded-md border border-border">
            {rows.map((m) => (
              <Row key={m.fixture_id} m={m} />
            ))}
          </ul>
        ) : null}
      </div>
    </Panel>
  );
}
