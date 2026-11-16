/**
 * «Estado de los precios» (plan maestro UX/UI 2026, decision 4; sheet C05): where the prices a reader sees stand - when
 * they were last read, how many of the followed matches have one and how many are late, the matches of the day without
 * a price and what PrediGol does with an old price. It reads GET /odds/status, the same judgement as the owner's «Salud
 * de cuotas»; the page exists only while FBI_ODDS_STATUS is on (the API says so in /auth/me).
 *
 * «Por casa» (BE-043, UX-143; decision D-06): a row per bookmaker with the matches it prices and their latest reading. The
 * book keeps one reading hour per match, not per bookmaker, so the hour is the matches' own and the page says so. The
 * sheet's strip of the last 24 hours is retired with its reason: nothing keeps a history of late spells by bookmaker, and
 * keeping one would change the odds' capture (outside this plan).
 */
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, CircleCheck, Clock, TriangleAlert } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { OddsStatus } from "@/lib/api/v1/types_odds_explorer";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatKickoff, formatRelative, formatTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, SkeletonCards } from "@/product/shared/States";

/** 1440 -> «24 h», 90 -> «90 min»: the distances of the rule, as a reader says them. */
export function pointText(minutes: number): string {
  return minutes >= 120 && minutes % 60 === 0
    ? t("odds.status.hours", { n: minutes / 60 })
    : t("odds.status.minutes", { n: minutes });
}

export function totals(data: OddsStatus): { fixtures: number; priced: number; late: number } {
  return data.by_horizon.reduce(
    (sum, h) => ({
      fixtures: sum.fixtures + h.fixtures,
      priced: sum.priced + h.with_price,
      late: sum.late + h.stale,
    }),
    { fixtures: 0, priced: 0, late: 0 },
  );
}

function Tag({ late }: { late: boolean }) {
  return (
    <span
      className={cn(
        "inline-flex h-6 shrink-0 items-center rounded-full px-2.5 text-xs font-semibold",
        late ? "bg-warning-soft text-warning" : "bg-positive-soft text-positive",
      )}
    >
      {t(late ? "odds.status.lateTag" : "odds.status.ok")}
    </span>
  );
}

export function ByBook({ data, total }: { data: OddsStatus; total: number }) {
  const books = data.by_book ?? [];
  return (
    <section aria-labelledby="os-books" data-testid="odds-status-books">
      <h2 id="os-books" className="text-title">
        {t("odds.status.byBook")}
      </h2>
      <ul className="card-surface mt-2 divide-y divide-border rounded-card">
        {books.map((b) => {
          const late = b.stale > 0;
          const share = total > 0 ? Math.min(1, b.matches / total) : 0;
          return (
            <li
              key={b.id}
              className="flex items-start gap-3 px-4 py-3"
              data-testid="odds-status-book"
            >
              <span
                aria-hidden
                className={cn(
                  "mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full",
                  late ? "bg-warning" : "bg-positive",
                )}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold">{b.name}</span>
                  <Tag late={late} />
                </div>
                <div className="numeric mt-0.5 text-[0.8125rem] text-muted-foreground">
                  {[
                    b.last_read_at ? formatRelative(b.last_read_at) : null,
                    t("odds.status.row", { priced: b.matches, total }),
                    ...(late ? [t("odds.status.rowLate", { count: b.stale })] : []),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </div>
                <div aria-hidden className="mt-2 h-1.5 overflow-hidden rounded-full bg-elevated">
                  <span
                    className={cn(
                      "block h-full rounded-full",
                      late ? "bg-muted-foreground/60" : "bg-positive",
                    )}
                    style={{ width: `${share * 100}%` }}
                  />
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      <p className="mt-2 text-[0.8125rem] text-muted-foreground">{t("odds.status.byBookNote")}</p>
    </section>
  );
}

function Body({ data }: { data: OddsStatus }) {
  const sum = totals(data);
  const late = sum.late > 0;
  const none = sum.priced === 0;
  return (
    <>
      <section
        className={cn("rounded-feature p-4", late || none ? "card-surface" : "surface-pitch")}
        aria-labelledby="os-now"
        data-testid="odds-status-now"
        data-state={none ? "none" : late ? "late" : "ok"}
      >
        <h2 id="os-now" className="flex items-center gap-2 text-subheading">
          {none ? (
            <Clock aria-hidden className="h-5 w-5 text-muted-foreground" />
          ) : late ? (
            <TriangleAlert aria-hidden className="h-5 w-5 text-warning" />
          ) : (
            <CircleCheck aria-hidden className="h-5 w-5 text-positive" />
          )}
          {t(none ? "odds.status.none" : late ? "odds.status.someLate" : "odds.status.upToDate")}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground" data-testid="odds-status-read">
          {data.last_read_at
            ? t("odds.status.lastRead", {
                when: formatRelative(data.last_read_at),
                exact: formatTime(data.last_read_at),
              })
            : t("odds.status.neverRead")}
        </p>
        <dl className="mt-4 grid grid-cols-2 gap-3">
          <div className="rounded-control bg-background-deep/60 px-3.5 py-3">
            <dt className="text-label text-subtle-foreground">{t("odds.status.withPrice")}</dt>
            <dd className="numeric mt-1.5 text-[1.5rem] font-extrabold leading-none">
              {t("odds.status.of", { n: sum.priced, total: sum.fixtures })}
            </dd>
          </div>
          <div className="rounded-control bg-background-deep/60 px-3.5 py-3">
            <dt className="text-label text-subtle-foreground">{t("odds.status.late")}</dt>
            <dd
              className={cn(
                "numeric mt-1.5 text-[1.5rem] font-extrabold leading-none",
                late && "text-warning",
              )}
            >
              {sum.late}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="os-when">
        <h2 id="os-when" className="text-title">
          {t("odds.status.byHorizon")}
        </h2>
        <ul className="card-surface mt-2 divide-y divide-border rounded-card">
          {data.by_horizon.map((h) => (
            <li
              key={h.horizon}
              className="flex items-center gap-3 px-4 py-3"
              data-testid="odds-status-horizon"
              data-horizon={h.horizon}
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-semibold">{t(`odds.status.horizon.${h.horizon}`)}</div>
                <div className="numeric mt-0.5 text-[0.8125rem] text-muted-foreground">
                  {h.fixtures === 0
                    ? t("odds.status.rowEmpty")
                    : [
                        t("odds.status.row", { priced: h.with_price, total: h.fixtures }),
                        ...(h.stale > 0 ? [t("odds.status.rowLate", { count: h.stale })] : []),
                      ].join(" · ")}
                </div>
              </div>
              {h.fixtures > 0 && h.with_price > 0 ? <Tag late={h.stale > 0} /> : null}
            </li>
          ))}
        </ul>
      </section>

      {data.by_book && data.by_book.length > 0 ? <ByBook data={data} total={sum.priced} /> : null}

      <section aria-labelledby="os-bare" data-testid="odds-status-bare">
        <div className="flex items-baseline justify-between gap-3">
          <h2 id="os-bare" className="text-title">
            {t("odds.status.withoutTitle")}
          </h2>
          {data.without_price_total > 0 ? (
            <span className="numeric text-[0.8125rem] text-muted-foreground">
              {t("odds.status.withoutCount", { count: data.without_price_total })}
            </span>
          ) : null}
        </div>
        {data.without_price.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">{t("odds.status.withoutNone")}</p>
        ) : (
          <ul className="card-surface mt-2 divide-y divide-border rounded-card">
            {data.without_price.map((m) => (
              <li key={m.fixture_id}>
                <Link
                  to="/matches/$fixtureId"
                  params={{ fixtureId: String(m.fixture_id) }}
                  className="block px-4 py-3 hover:bg-elevated/60"
                >
                  <div className="text-sm font-semibold">
                    {m.home} – {m.away}
                  </div>
                  <div className="mt-0.5 text-[0.8125rem] text-muted-foreground">
                    {m.competition} · {formatKickoff(m.kickoff_at)}
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
        {data.without_price_total > data.without_price.length ? (
          <p className="mt-2 text-[0.8125rem] text-muted-foreground">
            {t("odds.status.withoutMore", {
              count: data.without_price_total - data.without_price.length,
            })}
          </p>
        ) : null}
      </section>

      <section aria-labelledby="os-old">
        <h2 id="os-old" className="text-title">
          {t("odds.status.whatTitle")}
        </h2>
        <ul className="card-surface mt-2 space-y-3 rounded-card p-4 text-sm leading-relaxed">
          <li className="flex gap-2.5">
            <Clock aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            {t("odds.status.what1")}
          </li>
          <li className="flex gap-2.5" data-testid="odds-status-rule">
            <Clock aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            {t("odds.status.what2", {
              points: data.schedule_minutes.map(pointText).join(", "),
            })}
          </li>
          <li className="flex gap-2.5">
            <Clock aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            {t("odds.status.what3")}
          </li>
        </ul>
      </section>

      <p className="text-[0.8125rem] leading-relaxed text-muted-foreground">
        {t("odds.status.disclaimer")}
      </p>
    </>
  );
}

export function OddsStatusPage() {
  const open = useAuth().user?.odds_status === true;
  const q = useQuery({ ...live.oddsStatus, enabled: open, refetchInterval: 60_000 });
  return (
    <div className="mx-auto max-w-2xl space-y-5" data-testid="odds-status">
      <div>
        <Link
          to="/odds"
          className="tap-y relative inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft aria-hidden className="h-4 w-4" />
          {t("odds.status.back")}
        </Link>
        <h1 className="mt-2 text-display text-balance">{t("odds.status.title")}</h1>
        <p className="mt-1.5 text-[0.9375rem] text-muted-foreground">{t("odds.status.subtitle")}</p>
      </div>
      {!open ? (
        <EmptyState title={t("odds.status.closed")} />
      ) : q.isPending ? (
        <SkeletonCards count={3} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : q.data.data ? (
        <Body data={q.data.data} />
      ) : (
        <EmptyState title={t("odds.status.none")} />
      )}
    </div>
  );
}
