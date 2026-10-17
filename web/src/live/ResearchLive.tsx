/**
 * Backtesting and Settings, live and read-only. The backtest page shows the
 * protocol and the hyper-parameter search as they were run (validation season
 * only); the results live in Models. Settings shows the configuration the
 * running system actually uses - changed on the host, never from the browser.
 */
import { t } from "@/lib/i18n";
import { Link } from "@tanstack/react-router";
import { PageHeader } from "@/components/layout/PageHeader";
import { KeyValue, Panel, WarningBanner } from "@/components/primitives/Panel";
import {
  LimitedRows,
  TableShell,
  THead,
  TH,
  TRow,
  TD,
  TableSkeleton,
} from "@/components/primitives/DataTable";
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
import { CompetitionLogo, CountryFlag } from "@/components/football/Logos";
import { countryLabel } from "@/product/matches/country";
import type { CompetitionSummary } from "@/lib/api/v1/types";
import { localFixed } from "@/lib/i18n/format";

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
        title={t("admin.pages.backtesting.title")}
        description={t("admin.pages.backtesting.description")}
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
      <Panel
        title={t("research.common.protocol")}
        subtitle={t("research.backtesting.protocol.subtitle")}
      >
        <dl className="grid gap-x-8 sm:grid-cols-2 xl:grid-cols-3">
          <Fact
            label={t("research.common.competitions")}
            value={s.competitions.map((c) => c.name).join(", ")}
          />
          <Fact
            label={t("research.backtesting.protocol.validationSeason")}
            value={t("research.backtesting.protocol.validationValue", {
              season: seasonLabel(s.validation_season),
            })}
          />
          <Fact
            label={t("research.common.testSeason")}
            value={`${seasonLabel(s.test_season)} · ${utcDate(s.test_from)} – ${utcDate(s.test_to)}`}
          />
          <Fact label={t("research.backtesting.protocol.testFixtures")} value={int(s.n_targets)} />
          <Fact
            label={t("research.backtesting.protocol.refit")}
            value={t("research.backtesting.protocol.refitValue", {
              days: String(cfg["refit_days"] ?? "?"),
            })}
          />
          <Fact
            label={t("research.backtesting.protocol.cutoff")}
            value={t("research.backtesting.protocol.cutoffValue", {
              minutes: String(cfg["cutoff_offset_minutes"] ?? "?"),
            })}
          />
          <Fact
            label={t("research.backtesting.protocol.trainingWindow")}
            value={t("research.backtesting.protocol.trainingWindowValue", {
              days: String(cfg["history_days"] ?? "?"),
            })}
          />
          <Fact
            label={t("research.common.primaryBaseline")}
            value={baselineLabel(s.primary_baseline)}
          />
          <Fact label={t("research.common.finished")} value={utcDateTime(s.finished_at)} />
          <Fact label={t("research.common.codeVersion")} value={shortHash(s.code_version)} />
          <Fact label={t("research.common.datasetHash")} value={shortHash(s.dataset_hash)} />
          <Fact label={t("research.common.session")} value={shortHash(s.session_uuid, 8)} />
        </dl>
        <p className="mt-3 text-caption text-muted-foreground">
          {t("research.backtesting.protocol.checks")}{" "}
          <Link to="/admin/models" className="text-primary hover:underline">
            {t("research.backtesting.protocol.resultsLink")}
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
        title={t("research.backtesting.search.titleChosen", { model: MODEL_LABEL[kind] ?? kind })}
        subtitle={t("research.backtesting.search.subtitleChosen", {
          season: seasonLabel(sel.validation_season ?? null),
          xi: sel.chosen.xi,
          penalty: sel.chosen.penalty,
        })}
      >
        <p className="text-caption text-muted-foreground">
          {t("research.backtesting.search.notStored")}
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
      title={t("research.backtesting.search.title", { model: MODEL_LABEL[kind] ?? kind })}
      subtitle={t("research.backtesting.search.subtitle", {
        season: seasonLabel(sel.validation_season ?? null),
        xi: sel.chosen.xi,
        penalty: sel.chosen.penalty,
      })}
      bodyClassName=""
    >
      {extended ? (
        <p className="border-b border-border px-4 py-2 text-caption text-muted-foreground">
          {t("research.backtesting.search.extended")}
        </p>
      ) : null}
      <TableShell>
        <THead>
          <TH>{t("research.backtesting.search.corner")}</TH>
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
                        {localFixed(v, 5)}
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
        title={t("admin.pages.settings.title")}
        description={t("admin.pages.settings.description")}
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel
          title={t("research.settings.competitions.title")}
          subtitle={t("research.settings.competitions.subtitle")}
        >
          {comps.data ? (
            <TrackedCompetitions rows={comps.data.data} />
          ) : (
            <TableSkeleton rows={2} cols={2} />
          )}
        </Panel>
        <Panel
          title={t("research.settings.rule.title")}
          subtitle={t("research.settings.rule.subtitle")}
        >
          {rule ? (
            <>
              <KeyValue label={t("research.common.version")} value={String(rule["version"])} />
              <KeyValue
                label={t("research.common.markets")}
                value={(rule["markets"] as string[]).join(", ")}
              />
              <KeyValue
                label={t("research.settings.rule.oddsRange")}
                value={(rule["odds"] as string[]).join(" – ")}
              />
              <KeyValue label={t("research.settings.rule.minEv")} value={String(rule["min_ev"])} />
              <KeyValue
                label={t("research.settings.rule.minEdge")}
                value={String(rule["min_probability_edge"])}
              />
              <KeyValue
                label={t("research.settings.rule.publishing")}
                value={t("research.settings.rule.publishingValue")}
              />
            </>
          ) : (
            <TableSkeleton rows={3} cols={2} />
          )}
        </Panel>
        <Panel
          title={t("research.settings.analyst.title")}
          subtitle={t("research.settings.analyst.subtitle")}
        >
          {analyst.data ? (
            <>
              <KeyValue
                label={t("research.settings.analyst.languageModel")}
                value={
                  <StatusBadge tone={analyst.data.data.configured ? "positive" : "neutral"}>
                    {analyst.data.data.configured
                      ? t("research.settings.configured")
                      : t("research.settings.notConfigured")}
                  </StatusBadge>
                }
              />
              {analyst.data.data.missing.length ? (
                <KeyValue
                  label={t("research.settings.analyst.unset")}
                  value={analyst.data.data.missing.join(", ")}
                />
              ) : null}
              <KeyValue
                label={t("research.settings.analyst.tools")}
                value={int(analyst.data.data.tools.length)}
              />
            </>
          ) : (
            <TableSkeleton rows={2} cols={2} />
          )}
        </Panel>
        <Panel
          title={t("research.settings.notifications.title")}
          subtitle={t("research.settings.notifications.subtitle")}
        >
          {notes.data ? (
            <>
              <KeyValue
                label="Telegram"
                value={
                  <StatusBadge tone={notes.data.data.channel_configured ? "positive" : "neutral"}>
                    {notes.data.data.channel_configured
                      ? t("research.settings.configured")
                      : t("research.settings.notConfigured")}
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
          title={t("research.settings.recent.title")}
          subtitle={t("research.settings.recent.subtitle")}
          bodyClassName=""
        >
          <LimitedRows rows={notes.data.data.recent} step={15}>
            {(recent) => (
              <TableShell>
                <THead>
                  <TH>{t("research.settings.recent.created")}</TH>
                  <TH>{t("research.settings.recent.kind")}</TH>
                  <TH>{t("research.settings.recent.message")}</TH>
                  <TH>{t("research.settings.recent.status")}</TH>
                </THead>
                <tbody>
                  {recent.map((n) => (
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
                        <StatusBadge tone={notifyTone[n.status] ?? "neutral"}>
                          {n.status}
                        </StatusBadge>
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
            )}
          </LimitedRows>
        </Panel>
      ) : null}
      <WarningBanner tone="info">{t("research.settings.secrets")}</WarningBanner>
    </div>
  );
}

/**
 * The tracked competitions with their country: two "Bundesliga" or two "Serie A" are different leagues and the
 * list must say which. Sorted by country (international last), then name.
 */
export function TrackedCompetitions({ rows }: { rows: CompetitionSummary[] }) {
  const country = (c: CompetitionSummary) => countryLabel(c.country, c.country_code) ?? "\uffff";
  const tracked = rows
    .filter((c) => c.is_tracked)
    .sort((a, b) => country(a).localeCompare(country(b)) || a.name.localeCompare(b.name));
  return (
    <>
      <p className="mb-2 text-caption text-subtle-foreground">
        {t("research.settings.competitions.count", { n: tracked.length })}
      </p>
      <ul className="space-y-1 text-sm">
        {tracked.map((c) => (
          <li key={c.id} className="flex items-center justify-between gap-3">
            <span className="flex min-w-0 items-center gap-2">
              <CompetitionLogo src={c.logo_url} name={c.name} size={16} />
              <span className="min-w-0 break-words">{c.name}</span>
              <span className="flex shrink-0 items-center gap-1 text-caption text-subtle-foreground">
                <CountryFlag src={c.flag_url} name={c.country} height={10} />
                {countryLabel(c.country, c.country_code) ?? t("catalog.competitions.international")}
              </span>
            </span>
            <span className="numeric shrink-0 text-caption text-subtle-foreground">
              {t("research.settings.competitions.league", { id: c.provider_league_id })}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}
