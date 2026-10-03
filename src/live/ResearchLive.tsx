/**
 * Backtesting and Settings, live and read-only. The backtest page shows the
 * protocol and the hyper-parameter search as they were run (validation season
 * only); the results live in Models. Settings shows the configuration the
 * running system actually uses - changed on the host, never from the browser.
 */
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import { TableShell, THead, TH, TRow, TD, TableSkeleton } from "@/components/primitives/DataTable";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { Numeric } from "@/components/primitives/Indicators";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice, SectionView, StatusNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type { BacktestSessionSummary, SelectionInfo } from "@/lib/api/v1/types";
import { int } from "@/lib/format";
import { shortHash, utcDate, utcDateTime } from "./format";
import { baselineLabel, seasonLabel } from "./labels";
import { Fact } from "./shared";

const MODEL_LABEL: Record<string, string> = {
  poisson: "Poisson (Maher)",
  dixon_coles: "Dixon-Coles",
};

export function BacktestingLive() {
  const q = useLiveQuery(live.models);
  const d = q.data?.data;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "Research" }, { label: "Backtesting" }]}
        title="Backtesting"
        description="The walk-forward protocol as it was run. Nothing is re-run in the browser; results are in Models."
      />
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {!d ? (
        <TableSkeleton rows={5} cols={4} />
      ) : (
        <SectionView section={d.backtest}>{(s) => (s ? <SessionView s={s} /> : null)}</SectionView>
      )}
    </div>
  );
}

function SessionView({ s }: { s: BacktestSessionSummary }) {
  const cfg = s.config as Record<string, unknown>;
  return (
    <>
      <Panel title="Protocol" subtitle="Fixed before the test season was touched">
        <dl className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
          <Fact label="Competitions" value={s.competitions.map((c) => c.name).join(", ")} />
          <Fact
            label="Validation season"
            value={`${seasonLabel(s.validation_season)} — hyper-parameters only`}
          />
          <Fact
            label="Test season"
            value={`${seasonLabel(s.test_season)} · ${utcDate(s.test_from)} – ${utcDate(s.test_to)}`}
          />
          <Fact label="Test fixtures" value={int(s.n_targets)} />
          <Fact label="Refit" value={`every ${String(cfg["refit_days"] ?? "?")} day(s)`} />
          <Fact
            label="Cut-off"
            value={`${String(cfg["cutoff_offset_minutes"] ?? "?")} min before a block's first kick-off`}
          />
          <Fact
            label="Training window"
            value={`${String(cfg["history_days"] ?? "?")} days, results public 3 h after kick-off`}
          />
          <Fact label="Primary baseline" value={baselineLabel(s.primary_baseline)} />
          <Fact label="Finished" value={utcDateTime(s.finished_at)} />
          <Fact label="Code version" value={shortHash(s.code_version)} />
          <Fact label="Dataset hash" value={shortHash(s.dataset_hash)} />
          <Fact label="Session" value={shortHash(s.session_uuid, 8)} />
        </dl>
        <p className="mt-3 text-caption text-muted-foreground">
          Every block is checked: a training result not public before the cut-off, or a cut-off not
          before the kick-off it predicts, stops the run. A test rewrites all later results and
          requires every earlier prediction to come out identical.{" "}
          <Link to="/admin/models" className="text-primary hover:underline">
            Results against the market →
          </Link>
        </p>
      </Panel>
      {Object.entries(s.selection).map(([kind, sel]) => (
        <SearchGrid key={kind} kind={kind} sel={sel} />
      ))}
    </>
  );
}

function SearchGrid({ kind, sel }: { kind: string; sel: SelectionInfo }) {
  const scores = sel.validation_logloss ?? {};
  if (Object.keys(scores).length === 0) {
    return (
      <Panel
        title={`${MODEL_LABEL[kind] ?? kind} · hyper-parameters`}
        subtitle={`Chosen on ${seasonLabel(sel.validation_season ?? null)}: ξ=${sel.chosen.xi}, penalty=${sel.chosen.penalty}.`}
      >
        <p className="text-caption text-muted-foreground">
          This session stored the chosen values only, not the validation score of every candidate,
          so the search itself cannot be shown.
        </p>
      </Panel>
    );
  }
  const xis = sel.final_grid?.xi ?? [
    ...new Set(Object.keys(scores).map((k) => Number(k.split(",")[0]!.split("=")[1]))),
  ];
  const pens = sel.final_grid?.penalty ?? [
    ...new Set(Object.keys(scores).map((k) => Number(k.split(",")[1]!.split("=")[1]))),
  ];
  const score = (xi: number, pen: number) => scores[`xi=${xi},penalty=${pen}`] ?? null;
  const best = Math.min(...Object.values(scores));
  const extended =
    sel.initial_grid !== undefined &&
    (sel.final_grid?.xi.length !== sel.initial_grid.xi.length ||
      sel.final_grid?.penalty.length !== sel.initial_grid.penalty.length);
  return (
    <Panel
      title={`${MODEL_LABEL[kind] ?? kind} · hyper-parameter search`}
      subtitle={`Validation log loss on ${seasonLabel(sel.validation_season ?? null)}, on the fixtures every candidate predicted. Chosen: ξ=${sel.chosen.xi}, penalty=${sel.chosen.penalty}.`}
      bodyClassName=""
    >
      {extended ? (
        <p className="border-b border-border px-4 py-2 text-caption text-muted-foreground">
          The best candidate sat on the edge of the initial grid, so the grid was extended by a rule
          fixed in advance (validation scores only).
        </p>
      ) : null}
      <TableShell>
        <THead>
          <TH>ξ (per day) \ penalty</TH>
          {pens.map((p) => (
            <TH key={p} align="right">
              {p}
            </TH>
          ))}
        </THead>
        <tbody>
          {xis.map((xi) => (
            <TRow key={xi}>
              <TD className="numeric text-xs">{xi}</TD>
              {pens.map((p) => {
                const v = score(xi, p);
                const chosen = xi === sel.chosen.xi && p === sel.chosen.penalty;
                return (
                  <TD key={p} align="right">
                    {v === null ? (
                      <span className="text-subtle-foreground">—</span>
                    ) : (
                      <span
                        className={
                          chosen
                            ? "numeric font-semibold text-positive"
                            : v === best
                              ? "numeric text-positive"
                              : "numeric"
                        }
                      >
                        {v.toFixed(5)}
                      </span>
                    )}
                  </TD>
                );
              })}
            </TRow>
          ))}
        </tbody>
      </TableShell>
    </Panel>
  );
}

const notifyTone: Record<string, BadgeTone> = {
  sent: "positive",
  queued: "info",
  skipped: "neutral",
  failed: "negative",
};

export function SettingsLive() {
  const picks = useLiveQuery(live.picks);
  const analyst = useLiveQuery(live.analyst);
  const notes = useLiveQuery(live.notifications);
  const comps = useLiveQuery(live.competitions);
  const rule = picks.data?.data.rule;
  return (
    <div className="space-y-4">
      <PageHeader
        breadcrumb={[{ label: "System" }, { label: "Settings" }]}
        title="Settings"
        description="The configuration the running system uses, read-only. It changes on the host (.env, config/competitions.yaml, a new rule version) - never from the browser."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title="Tracked competitions"
          subtitle="config/competitions.yaml, applied with scripts.manage_competitions"
        >
          {comps.data ? (
            <ul className="space-y-1 text-sm">
              {comps.data.data
                .filter((c) => c.is_tracked)
                .map((c) => (
                  <li key={c.id} className="flex justify-between gap-3">
                    <span>{c.name}</span>
                    <span className="numeric text-caption text-subtle-foreground">
                      league {c.provider_league_id}
                    </span>
                  </li>
                ))}
            </ul>
          ) : (
            <TableSkeleton rows={2} cols={2} />
          )}
        </Panel>
        <Panel title="Decision rule" subtitle="Versioned; a threshold change is a new version">
          {rule ? (
            <>
              <KeyValue label="Version" value={String(rule["version"])} />
              <KeyValue label="Markets" value={(rule["markets"] as string[]).join(", ")} />
              <KeyValue label="Odds range" value={(rule["odds"] as string[]).join(" – ")} />
              <KeyValue label="Minimum EV" value={String(rule["min_ev"])} />
              <KeyValue
                label="Minimum probability edge"
                value={String(rule["min_probability_edge"])}
              />
              <KeyValue label="Publishing" value="disabled in the schema" />
            </>
          ) : (
            <TableSkeleton rows={3} cols={2} />
          )}
        </Panel>
        <Panel
          title="AI analyst"
          subtitle="FBI_ANALYST_API_KEY / FBI_ANALYST_MODEL on the API host"
        >
          {analyst.data ? (
            <>
              <KeyValue
                label="Language model"
                value={
                  <StatusBadge tone={analyst.data.data.configured ? "positive" : "neutral"}>
                    {analyst.data.data.configured ? "configured" : "not configured"}
                  </StatusBadge>
                }
              />
              {analyst.data.data.missing.length ? (
                <KeyValue label="Unset" value={analyst.data.data.missing.join(", ")} />
              ) : null}
              <KeyValue label="Tools" value={int(analyst.data.data.tools.length)} />
            </>
          ) : (
            <TableSkeleton rows={2} cols={2} />
          )}
        </Panel>
        <Panel
          title="Notifications (bot)"
          subtitle="Informational only. FBI_TELEGRAM_BOT_TOKEN / FBI_TELEGRAM_CHAT_ID on the host"
        >
          {notes.data ? (
            <>
              <KeyValue
                label="Telegram"
                value={
                  <StatusBadge tone={notes.data.data.channel_configured ? "positive" : "neutral"}>
                    {notes.data.data.channel_configured ? "configured" : "not configured"}
                  </StatusBadge>
                }
              />
              {Object.entries(notes.data.data.by_status).map(([k, v]) => (
                <KeyValue key={k} label={k} value={int(v)} />
              ))}
              {notes.data.status !== "ok" ? (
                <StatusNotice status={notes.data.status} reason={notes.data.reason} compact />
              ) : null}
            </>
          ) : (
            <TableSkeleton rows={2} cols={2} />
          )}
        </Panel>
      </div>
      {notes.data?.data.recent.length ? (
        <Panel
          title="Recent messages"
          subtitle="What the bot produced and what happened to each"
          bodyClassName=""
        >
          <TableShell>
            <THead>
              <TH>Created</TH>
              <TH>Kind</TH>
              <TH>Message</TH>
              <TH>Status</TH>
            </THead>
            <tbody>
              {notes.data.data.recent.map((n) => (
                <TRow key={n.id}>
                  <TD>
                    <Numeric muted>{utcDateTime(n.created_at)}</Numeric>
                  </TD>
                  <TD className="text-xs text-muted-foreground">{n.kind}</TD>
                  <TD>
                    <div className="text-sm">{n.title}</div>
                    <div className="whitespace-pre-line text-caption text-subtle-foreground">
                      {n.body}
                    </div>
                  </TD>
                  <TD>
                    <StatusBadge tone={notifyTone[n.status] ?? "neutral"}>{n.status}</StatusBadge>
                    {n.last_error ? (
                      <div className="mt-0.5 text-caption text-subtle-foreground">
                        {n.last_error}
                      </div>
                    ) : null}
                  </TD>
                </TRow>
              ))}
            </tbody>
          </TableShell>
        </Panel>
      ) : null}
      <WarningBanner tone="info">
        Keys and tokens live only on the host. The browser receives whether something is configured,
        never its value.
      </WarningBanner>
    </div>
  );
}
