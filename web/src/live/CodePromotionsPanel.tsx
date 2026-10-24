/**
 * The model code against its promotions (plan F12) in Evolución: every fingerprint of the model packages that
 * production forecast with in the last 30 days, the decision on record that covers each (who, when, why, on what
 * evidence), the plan's count "changes with their promotion traced / changes", and whether the code this server runs is
 * the one the ledger has in force. Reading only - it changes no model, rule or pick; the ledger is written in the same
 * commit as the change of code and copied to the database at a release. A change older than the ledger is listed apart
 * and never counted: the past cannot be decided afterwards.
 */
import { t, translateOr } from "@/lib/i18n";
import { localInt, localPct } from "@/lib/i18n/format";
import { Panel } from "@/components/primitives/Panel";
import { StatusBadge, type BadgeTone } from "@/components/primitives/StatusBadge";
import { TableSkeleton } from "@/components/primitives/DataTable";
import { useLiveQuery } from "@/components/system/dataSourcesContext";
import { ApiErrorNotice } from "@/components/system/LiveState";
import { live } from "@/lib/api/v1/queries";
import type {
  CodeFingerprint,
  CodeLedgerEntry,
  CodePromotionRow,
  CodePromotions,
  CodeStatus,
} from "@/lib/api/v1/types_ai";
import { Note, Stat, StatGrid, SubTitle } from "./AiBits";
import {
  OTHER_ORDER,
  newestFirst,
  ordered,
  producedText,
  statusHelp,
  statusText,
} from "./codeModel";
import { utcDateTime } from "./format";

const DASH = "—";
/** What the server calls the versions keyed by a repository commit (before 5 Oct 2026). */
const LEGACY = "legacy";
const STATUS_TONE: Record<CodeStatus, BadgeTone> = {
  BASELINE: "info",
  PROMOTED: "positive",
  AFTER_USE: "warning",
  PENDING_SYNC: "warning",
  UNTRACED: "negative",
  PRE_LEDGER: "neutral",
};

function Evidence({ value }: { value: Record<string, unknown> }) {
  if (!Object.keys(value).length) return null;
  return (
    <details className="text-caption text-subtle-foreground">
      <summary className="tap relative cursor-pointer">{t("ai.evolution.evidence")}</summary>
      <pre className="mt-1 max-h-48 overflow-auto rounded border border-border bg-card p-2">
        {JSON.stringify(value, null, 2)}
      </pre>
    </details>
  );
}

function PromotionNote({ p }: { p: CodePromotionRow }) {
  return (
    <div className="space-y-1 rounded border border-border bg-elevated/40 p-2">
      <p className="text-caption font-medium text-foreground">
        {t("ai.evolution.code.promotion", {
          id: p.id,
          who: p.decided_by,
          when: utcDateTime(p.decided_at),
        })}
      </p>
      <p className="text-xs text-muted-foreground">{p.reason}</p>
      <Evidence value={p.evidence} />
    </div>
  );
}

function FingerprintCard({ f, running }: { f: CodeFingerprint; running: string }) {
  const legacy = f.fingerprint === LEGACY;
  const help = statusHelp(f.status);
  return (
    <li
      className="space-y-1.5 rounded-md border border-border p-3"
      data-testid={`code-fingerprint-${f.fingerprint}`}
      data-status={f.status}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="numeric text-sm font-medium">
          {legacy ? t("ai.evolution.code.legacy") : f.fingerprint}
        </span>
        <StatusBadge tone={STATUS_TONE[f.status]}>{statusText(f.status)}</StatusBadge>
        {f.fingerprint === running ? (
          <StatusBadge tone="brand" dot={false}>
            {t("ai.evolution.code.running")}
          </StatusBadge>
        ) : null}
        {f.in_force_now && f.fingerprint !== running ? (
          <span className="text-caption text-subtle-foreground">
            {t("ai.evolution.code.recent")}
          </span>
        ) : null}
      </div>
      <p className="text-caption text-subtle-foreground">
        {t("ai.evolution.code.appeared", { when: utcDateTime(f.appeared_at) })} ·{" "}
        {t("ai.evolution.code.lastUse", { when: utcDateTime(f.last_use) })}
      </p>
      <p className="text-caption text-subtle-foreground">
        {t("ai.evolution.code.versions", { count: f.versions, models: f.models.join(", ") })} ·{" "}
        {producedText(f.rows)}
      </p>
      {help ? <p className="text-caption text-muted-foreground">{help}</p> : null}
      {legacy ? (
        <p className="text-caption text-muted-foreground">{t("ai.evolution.code.legacyHelp")}</p>
      ) : null}
      {f.promotion ? (
        <PromotionNote p={f.promotion} />
      ) : f.status !== "PRE_LEDGER" ? (
        <p className="text-caption font-medium text-negative">
          {t("ai.evolution.code.noPromotion")}
        </p>
      ) : null}
    </li>
  );
}

function LedgerRow({ e }: { e: CodeLedgerEntry }) {
  return (
    <li
      className="space-y-1 border-b border-border pb-2 last:border-0"
      data-testid={`code-ledger-${e.fingerprint}`}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="numeric font-medium">{e.fingerprint}</span>
        {e.baseline ? (
          <StatusBadge tone="info" dot={false}>
            {t("ai.evolution.code.ledger.baseline")}
          </StatusBadge>
        ) : null}
        <StatusBadge tone={e.recorded ? "positive" : "warning"} dot={false}>
          {e.recorded
            ? t("ai.evolution.code.ledger.recorded")
            : t("ai.evolution.code.ledger.pending")}
        </StatusBadge>
        <StatusBadge tone={e.used ? "brand" : "neutral"} dot={false}>
          {e.used ? t("ai.evolution.code.ledger.used") : t("ai.evolution.code.ledger.unused")}
        </StatusBadge>
      </div>
      <p className="text-caption text-subtle-foreground">
        {t("ai.evolution.code.ledger.by", {
          who: e.decided_by,
          phase: e.phase,
          when: utcDateTime(e.decided_at),
        })}
      </p>
      <p className="text-xs text-muted-foreground">{e.reason}</p>
      <Evidence value={e.evidence} />
    </li>
  );
}

function Tiles({ d }: { d: CodePromotions }) {
  const c = d.counts;
  const coverageTone =
    c.counted === 0
      ? "muted"
      : c.untraced > 0
        ? "negative"
        : c.traced < c.counted
          ? "warning"
          : "positive";
  return (
    <StatGrid testId="code-tiles">
      <Stat
        label={t("ai.evolution.code.tiles.coverage")}
        value={
          c.counted
            ? t("ai.evolution.code.tiles.coverageValue", {
                traced: localInt(c.traced),
                counted: localInt(c.counted),
              })
            : t("ai.evolution.code.tiles.coverageNone")
        }
        hint={
          d.coverage === null
            ? t("ai.evolution.code.tiles.coverageHintNone")
            : t("ai.evolution.code.tiles.coverageHint", { percent: localPct(d.coverage, 0) })
        }
        tone={coverageTone}
      />
      <Stat
        label={t("ai.evolution.code.tiles.running")}
        value={d.running_code}
        hint={
          d.in_force_matches_running
            ? t("ai.evolution.code.tiles.runningMatches")
            : t("ai.evolution.code.tiles.runningDiffers", { code: d.ledger_in_force ?? DASH })
        }
        tone={d.in_force_matches_running ? "default" : "warning"}
      />
      <Stat
        label={t("ai.evolution.code.tiles.fingerprints")}
        value={localInt(c.fingerprints)}
        hint={
          c.pre_ledger
            ? t("ai.evolution.code.tiles.fingerprintsHint", { count: c.pre_ledger })
            : t("ai.evolution.code.tiles.fingerprintsHintNone")
        }
      />
      <Stat
        label={t("ai.evolution.code.tiles.ledgerSince")}
        value={d.ledger_since ? utcDateTime(d.ledger_since) : DASH}
        hint={t("ai.evolution.code.tiles.ledgerSinceHint", { days: d.days })}
      />
    </StatGrid>
  );
}

function Others({ other }: { other: Record<string, number> }) {
  const keys = ordered(Object.keys(other), OTHER_ORDER);
  if (!keys.length) return null;
  return (
    <div className="space-y-1.5">
      <SubTitle>{t("ai.evolution.code.other.title")}</SubTitle>
      <ul
        className="flex flex-wrap gap-1.5 text-caption text-subtle-foreground"
        data-testid="code-other"
      >
        {keys.map((k) => (
          <li key={k} className="rounded border border-border bg-elevated/50 px-1.5 py-0.5">
            {translateOr(`ai.evolution.code.other.${k}`, k)}{" "}
            <span className="numeric text-foreground">{localInt(other[k] ?? 0)}</span>
          </li>
        ))}
      </ul>
      <Note>{t("ai.evolution.code.other.help")}</Note>
    </div>
  );
}

/** The panel's content for one answer of the server. */
export function CodePromotionsBody({ d }: { d: CodePromotions }) {
  const counted = newestFirst(d.fingerprints.filter((f) => f.status !== "PRE_LEDGER"));
  const before = newestFirst(d.fingerprints.filter((f) => f.status === "PRE_LEDGER"));
  return (
    <div className="space-y-4" data-testid="code-promotions">
      <Tiles d={d} />
      <Note>{t("ai.evolution.code.measured", { when: utcDateTime(d.now) })}</Note>
      <section className="space-y-2" data-testid="code-counted">
        <SubTitle>{t("ai.evolution.code.counted.title")}</SubTitle>
        {counted.length === 0 ? (
          <Note>{t("ai.evolution.code.counted.empty")}</Note>
        ) : (
          <ul className="space-y-2">
            {counted.map((f) => (
              <FingerprintCard key={f.fingerprint} f={f} running={d.running_code} />
            ))}
          </ul>
        )}
      </section>
      {before.length ? (
        <details className="space-y-2" data-testid="code-before">
          <summary className="tap relative cursor-pointer text-caption font-medium uppercase tracking-wider text-subtle-foreground">
            {t("ai.evolution.code.before.title", { count: before.length })}
          </summary>
          <div className="mt-2 space-y-2">
            <Note>{t("ai.evolution.code.before.help")}</Note>
            <ul className="space-y-2">
              {before.map((f) => (
                <FingerprintCard key={f.fingerprint} f={f} running={d.running_code} />
              ))}
            </ul>
          </div>
        </details>
      ) : null}
      <section className="space-y-2" data-testid="code-ledger">
        <SubTitle>{t("ai.evolution.code.ledger.title")}</SubTitle>
        <Note>{t("ai.evolution.code.ledger.subtitle")}</Note>
        {d.ledger.length === 0 ? (
          <Note>{t("ai.evolution.code.ledger.empty")}</Note>
        ) : (
          <ul className="space-y-2">
            {[...d.ledger].reverse().map((e) => (
              <LedgerRow key={e.fingerprint} e={e} />
            ))}
          </ul>
        )}
      </section>
      <Others other={d.other} />
      <Note>{t("ai.evolution.code.how")}</Note>
    </div>
  );
}

export function CodePromotionsPanel() {
  const q = useLiveQuery(live.codePromotions());
  const d = q.data?.data ?? null;
  return (
    <Panel
      title={t("ai.evolution.code.title")}
      subtitle={t("ai.evolution.code.subtitle")}
      actions={
        <button
          type="button"
          disabled={q.isFetching}
          onClick={() => void q.refetch()}
          className="h-7 rounded-md border border-border px-2.5 text-xs font-medium hover:bg-elevated disabled:opacity-50"
        >
          {t("ai.evolution.code.refresh")}
        </button>
      }
    >
      {q.isError ? <ApiErrorNotice error={q.error} /> : null}
      {q.isLoading ? <TableSkeleton rows={3} cols={4} /> : null}
      {d ? <CodePromotionsBody d={d} /> : null}
    </Panel>
  );
}
