/**
 * The reader's privacy, in their profile (plan UX, A4; Ley 1581 de 2012): what they accepted and when, withdrawing the
 * processing authorisation, a copy of everything PrediGol keeps about them, and their queries, claims and deletion
 * requests with the legal deadline in sight. Always reachable, even when the consent gate stops the product.
 */
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Download, FileText, Loader2, MessageSquare } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import type {
  ConsentPurpose,
  ConsentRecord,
  PrivacyRequest,
  PrivacyRequestKind,
} from "@/lib/api/v1/types_customer";
import { t, useI18n } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ErrorState, errorMessage } from "@/product/shared/States";
import { LEGAL_DOCUMENTS, dayOf, legalPath } from "@/product/legal/links";

const INPUT =
  "mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none pointer-coarse:h-11";
const BUTTON =
  "tap-y relative inline-flex h-9 items-center gap-2 rounded-md px-4 text-sm font-semibold disabled:opacity-50 pointer-coarse:h-11";
const KINDS: readonly PrivacyRequestKind[] = ["privacy_query", "privacy_claim", "privacy_deletion"];

function Subtitle({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 mt-1 text-sm font-semibold">{children}</h3>;
}

function latestOf(history: readonly ConsentRecord[], kind: string): ConsentRecord | undefined {
  return history.find((r) => r.kind === kind);
}

function ConsentRow({
  purpose,
  latest,
  onDecide,
  busy,
}: {
  purpose: ConsentPurpose;
  latest: ConsentRecord | undefined;
  onDecide: (granted: boolean) => Promise<void>;
  busy: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const outdated = latest?.granted && latest.version !== purpose.version && purpose.changes;
  return (
    <li className="space-y-1 py-3" data-testid={`privacy-consent-${purpose.kind}`}>
      <p className="text-sm">{purpose.statement}</p>
      <p className="text-caption text-muted-foreground">
        {!latest
          ? t("legal.privacy.pending")
          : latest.granted
            ? t("legal.privacy.accepted", {
                date: formatDateTime(latest.at),
                version: latest.version,
              })
            : t("legal.privacy.withdrawn", { date: formatDateTime(latest.at) })}
        {outdated ? <span className="block">{t("legal.privacy.outdated")}</span> : null}
      </p>
      {purpose.withdrawable && latest?.granted ? (
        confirming ? (
          <div className="space-y-2 rounded-md border border-negative/30 bg-negative-soft p-3">
            <p className="text-xs">{t("legal.privacy.withdrawConfirm")}</p>
            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy}
                data-testid="privacy-withdraw-confirm"
                onClick={() => void onDecide(false).then(() => setConfirming(false))}
                className={cn(BUTTON, "bg-negative text-negative-foreground")}
              >
                {t("legal.privacy.withdrawYes")}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                className={cn(BUTTON, "border border-border-strong font-medium")}
              >
                {t("legal.privacy.cancel")}
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            data-testid="privacy-withdraw"
            onClick={() => setConfirming(true)}
            className={cn(BUTTON, "border border-negative/40 font-medium text-negative")}
          >
            {t("legal.privacy.withdraw")}
          </button>
        )
      ) : null}
      {/* A reader who withdrew it can give it again here (with the gate on, the gate asks for it anyway). */}
      {purpose.withdrawable && latest && !latest.granted ? (
        <button
          type="button"
          disabled={busy}
          data-testid="privacy-regrant"
          onClick={() => void onDecide(true)}
          className={cn(BUTTON, "border border-border-strong font-medium")}
        >
          {t("legal.privacy.regrant")}
        </button>
      ) : null}
    </li>
  );
}

function ConsentsSection() {
  const qc = useQueryClient();
  const { locale } = useI18n();
  const state = useQuery({
    queryKey: ["me", "consents", locale],
    queryFn: () => v1.myConsents(locale),
  });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function decide(purpose: ConsentPurpose, granted: boolean) {
    setBusy(true);
    setFailure(null);
    try {
      await v1.decideConsents({
        decisions: [{ kind: purpose.kind, granted, version: purpose.version }],
        locale,
        source: "profile",
      });
      await qc.invalidateQueries({ queryKey: ["me", "consents"] });
      await qc.invalidateQueries({ queryKey: ["auth", "me"] });
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  if (state.isPending) return <Loader2 aria-hidden className="h-4 w-4 animate-spin" />;
  if (state.isError) return <ErrorState error={state.error} onRetry={() => void state.refetch()} />;
  const { purposes, history } = state.data;
  return (
    <div data-testid="privacy-consents">
      <Subtitle>{t("legal.privacy.consentsTitle")}</Subtitle>
      <ul className="divide-y divide-border/70">
        {purposes.map((p) => (
          <ConsentRow
            key={p.kind}
            purpose={p}
            latest={latestOf(history, p.kind)}
            busy={busy}
            onDecide={(granted) => decide(p, granted)}
          />
        ))}
      </ul>
      {failure ? (
        <p role="alert" className="text-xs text-negative">
          {failure}
        </p>
      ) : null}
      {history.length ? (
        <details className="mt-2 rounded-md border border-border">
          <summary className="flex min-h-11 cursor-pointer items-center px-3 text-xs font-medium">
            {t("legal.privacy.history")}
          </summary>
          <ul className="space-y-2 px-3 pb-3 text-xs" data-testid="privacy-history">
            {history.map((r, i) => (
              <li key={`${r.kind}-${r.at}-${i}`}>
                <span className="font-medium">
                  {r.granted
                    ? t("legal.privacy.historyGranted")
                    : t("legal.privacy.historyWithdrawn")}
                </span>{" "}
                · {r.statement}
                <span className="block text-muted-foreground">
                  {t("legal.privacy.historyMeta", {
                    date: formatDateTime(r.at),
                    version: r.version,
                    source: t(`legal.privacy.source.${r.source}`),
                  })}
                </span>
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

function download(doc: unknown, locale: string) {
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${locale === "en" ? "predigol-data" : "predigol-datos"}-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

/** The password again - and the code when the account has a second factor - before data leaves or is deleted. */
function Reauth({
  needsCode,
  password,
  code,
  setPassword,
  setCode,
}: {
  needsCode: boolean;
  password: string;
  code: string;
  setPassword: (v: string) => void;
  setCode: (v: string) => void;
}) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("legal.privacy.password")}</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          data-testid="privacy-password"
          onChange={(e) => setPassword(e.target.value)}
          className={INPUT}
        />
      </label>
      {needsCode ? (
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("legal.privacy.code")}</span>
          <input
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\s/g, ""))}
            className={INPUT}
          />
        </label>
      ) : null}
    </div>
  );
}

function ExportSection() {
  const auth = useAuth();
  const { locale } = useI18n();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const needsCode = Boolean(auth.user?.mfa_enabled);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const doc = await v1.exportMyData({ password, code: needsCode ? code : null });
      download(doc, locale);
      setPassword("");
      setCode("");
      setOpen(false);
      setMessage({ ok: true, text: t("legal.privacy.exported") });
    } catch (err) {
      setMessage({ ok: false, text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="privacy-export">
      <Subtitle>{t("legal.privacy.exportTitle")}</Subtitle>
      <p className="mb-3 text-xs text-muted-foreground">{t("legal.privacy.exportHelp")}</p>
      {open ? (
        <form onSubmit={(e) => void submit(e)} className="space-y-3">
          <Reauth
            needsCode={needsCode}
            password={password}
            code={code}
            setPassword={setPassword}
            setCode={setCode}
          />
          <div className="flex flex-wrap gap-2">
            <button
              type="submit"
              disabled={busy || !password || (needsCode && code.length < 6)}
              data-testid="privacy-export-confirm"
              className={cn(BUTTON, "bg-primary text-primary-foreground")}
            >
              {busy ? (
                <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
              ) : (
                <Download aria-hidden className="h-4 w-4" />
              )}
              {t("legal.privacy.confirm")}
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className={cn(BUTTON, "border border-border-strong font-medium")}
            >
              {t("legal.privacy.cancel")}
            </button>
          </div>
        </form>
      ) : (
        <button
          type="button"
          data-testid="privacy-export-start"
          onClick={() => {
            setOpen(true);
            setMessage(null);
          }}
          className={cn(BUTTON, "border border-border-strong font-medium")}
        >
          <Download aria-hidden className="h-4 w-4" />
          {t("legal.privacy.exportButton")}
        </button>
      )}
      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={cn("mt-2 text-xs", message.ok ? "text-positive" : "text-negative")}
        >
          {message.text}
        </p>
      ) : null}
    </div>
  );
}

function RequestCard({ request }: { request: PrivacyRequest }) {
  return (
    <li
      className="space-y-2 rounded-md border border-border p-3"
      data-testid="privacy-request"
      data-kind={request.kind}
      data-status={request.status}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">{t(`legal.privacy.kind.${request.kind}`)}</span>
        <span className="rounded-full border border-border px-2 py-0.5 text-caption">
          {t(`legal.privacy.status.${request.status}`)}
        </span>
      </div>
      <p className="text-caption text-muted-foreground">
        {t("legal.privacy.opened", { date: formatDateTime(request.opened_at) })}
        {request.status !== "closed" && request.deadline ? (
          <span className="block font-medium text-foreground" data-testid="privacy-deadline">
            {request.extended_to
              ? t("legal.privacy.extended", { date: dayOf(request.extended_to) })
              : t("legal.privacy.deadline", { date: dayOf(request.deadline) })}
          </span>
        ) : null}
      </p>
      <ul className="space-y-1.5">
        {request.messages.map((m, i) => (
          <li key={`${m.at}-${i}`} className="text-xs">
            <span className="font-semibold">{t(`legal.privacy.author.${m.author}`)}</span>
            <span className="text-muted-foreground"> · {formatDateTime(m.at)}</span>
            <p className="whitespace-pre-line break-words">{m.body}</p>
          </li>
        ))}
      </ul>
    </li>
  );
}

function RequestsSection() {
  const auth = useAuth();
  const qc = useQueryClient();
  const requests = useQuery({
    queryKey: ["me", "privacy-requests"],
    queryFn: v1.myPrivacyRequests,
  });
  const [kind, setKind] = useState<PrivacyRequestKind>("privacy_query");
  const [message, setMessage] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const deletion = kind === "privacy_deletion";
  const needsCode = deletion && Boolean(auth.user?.mfa_enabled);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setResult(null);
    try {
      const created = await v1.openPrivacyRequest({
        kind,
        message: message.trim(),
        ...(deletion ? { password, code: needsCode ? code : null } : {}),
      });
      setMessage("");
      setPassword("");
      setCode("");
      setResult({
        ok: true,
        text: t("legal.privacy.sent", { date: created.deadline ? dayOf(created.deadline) : "—" }),
      });
      await qc.invalidateQueries({ queryKey: ["me", "privacy-requests"] });
    } catch (err) {
      setResult({ ok: false, text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div data-testid="privacy-requests">
      <Subtitle>{t("legal.privacy.requestsTitle")}</Subtitle>
      <p className="mb-3 text-xs text-muted-foreground">{t("legal.privacy.requestsHelp")}</p>
      {requests.isPending ? (
        <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
      ) : requests.isError ? (
        <ErrorState error={requests.error} onRetry={() => void requests.refetch()} />
      ) : requests.data.length ? (
        <ul className="mb-4 space-y-2">
          {requests.data.map((r) => (
            <RequestCard key={r.id} request={r} />
          ))}
        </ul>
      ) : (
        <p className="mb-4 text-xs text-muted-foreground">{t("legal.privacy.none")}</p>
      )}
      <form onSubmit={(e) => void submit(e)} className="space-y-3">
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("legal.privacy.kindLabel")}</span>
          <select
            value={kind}
            data-testid="privacy-kind"
            onChange={(e) => setKind(e.target.value as PrivacyRequestKind)}
            className={INPUT}
          >
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`legal.privacy.kind.${k}`)}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("legal.privacy.message")}</span>
          <textarea
            value={message}
            maxLength={4000}
            rows={3}
            data-testid="privacy-message"
            onChange={(e) => setMessage(e.target.value)}
            className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
          />
        </label>
        {deletion ? (
          <>
            <p className="rounded-md border border-negative/30 bg-negative-soft px-3 py-2 text-xs">
              {t("legal.privacy.deletionWarning")}
            </p>
            <Reauth
              needsCode={needsCode}
              password={password}
              code={code}
              setPassword={setPassword}
              setCode={setCode}
            />
          </>
        ) : null}
        <button
          type="submit"
          data-testid="privacy-send"
          disabled={busy || !message.trim() || (deletion && !password)}
          className={cn(
            BUTTON,
            deletion
              ? "bg-negative text-negative-foreground"
              : "bg-primary text-primary-foreground",
          )}
        >
          {busy ? (
            <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
          ) : (
            <MessageSquare aria-hidden className="h-4 w-4" />
          )}
          {t("legal.privacy.send")}
        </button>
        {result ? (
          <p
            role={result.ok ? "status" : "alert"}
            data-testid="privacy-result"
            className={cn("text-xs", result.ok ? "text-positive" : "text-negative")}
          >
            {result.text}
          </p>
        ) : null}
      </form>
    </div>
  );
}

export function PrivacyPanel() {
  return (
    <div className="space-y-6" data-testid="privacy-panel">
      <p className="text-xs text-muted-foreground">{t("legal.privacy.help")}</p>
      <ConsentsSection />
      <ExportSection />
      <RequestsSection />
      <div>
        <Subtitle>{t("legal.privacy.documents")}</Subtitle>
        <ul className="flex flex-wrap gap-2">
          {LEGAL_DOCUMENTS.map((d) => (
            <li key={d}>
              <Link
                to="/legal/$doc"
                params={{ doc: legalPath(d).slice("/legal/".length) }}
                className="tap-y relative inline-flex items-center gap-1.5 rounded-md border border-border-strong px-3 py-1.5 text-xs hover:bg-elevated"
              >
                <FileText aria-hidden className="h-3.5 w-3.5" />
                {t(`legal.doc.${d}`)}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
