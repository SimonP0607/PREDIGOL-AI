/**
 * The steps that finish signing in, after a right password: the second factor (a code from the authenticator app
 * or a recovery code), setting the authenticator up when the role requires one, and choosing a new password after
 * an administrator's reset. The API decides which step is owed (Me.stage); every other route answers 403 until it
 * is done.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import {
  Check,
  Copy,
  Download,
  KeyRound,
  Loader2,
  LogOut,
  ShieldCheck,
  Smartphone,
} from "lucide-react";
import { BrandCrest } from "@/components/brand/Brand";
import { LanguageSwitch } from "@/components/layout/HeaderControls";
import { useAuth } from "@/lib/auth/AuthProvider";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import type { Me, MfaEnrollment } from "@/lib/api/v1/types_auth";
import { t } from "@/lib/i18n";
import { stepError } from "./stepError";
import { cn } from "@/lib/utils";

const field =
  "mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none focus-visible:ring-1 focus-visible:ring-ring";
const primary =
  "flex h-10 w-full items-center justify-center gap-2 rounded-md bg-primary text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60";

function Shell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  const auth = useAuth();
  return (
    <div className="pitch-glow relative flex min-h-screen flex-col bg-background">
      <div className="flex justify-end p-4">
        <LanguageSwitch />
      </div>
      <main className="flex flex-1 items-center justify-center px-4 pb-16">
        <div className="w-full max-w-md">
          <div className="flex flex-col items-center text-center">
            <BrandCrest size={96} />
            <h1 className="mt-4 font-display text-2xl font-bold tracking-tight">{title}</h1>
            <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>
          </div>
          <div className="mt-6 space-y-4 rounded-xl border border-border bg-card/90 p-5 shadow-xl backdrop-blur">
            {children}
          </div>
          <button
            type="button"
            onClick={() => void auth.signOut()}
            data-testid="step-cancel"
            className="mx-auto mt-4 flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground"
          >
            <LogOut aria-hidden className="h-3.5 w-3.5" />
            {t("auth.steps.cancel")}
          </button>
        </div>
      </main>
    </div>
  );
}

function Alert({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <p
      role="alert"
      data-testid="step-error"
      className="rounded-md border border-negative/40 bg-negative-soft px-3 py-2 text-xs text-negative"
    >
      {text}
    </p>
  );
}

function CodeInput({
  value,
  onChange,
  recovery,
}: {
  value: string;
  onChange: (v: string) => void;
  recovery: boolean;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-muted-foreground">
        {recovery ? t("auth.steps.recoveryCode") : t("auth.steps.code")}
      </span>
      <input
        name={recovery ? "recovery-code" : "one-time-code"}
        autoComplete={recovery ? "off" : "one-time-code"}
        inputMode={recovery ? "text" : "numeric"}
        maxLength={recovery ? 24 : 7}
        autoFocus
        value={value}
        onChange={(e) =>
          onChange(recovery ? e.target.value : e.target.value.replace(/[^0-9 ]/g, ""))
        }
        data-testid="step-code"
        className={cn(field, "numeric text-center text-lg tracking-[0.35em]")}
      />
    </label>
  );
}

function MfaStep() {
  const auth = useAuth();
  const [recovery, setRecovery] = useState(false);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const who = await v1.verifyMfa(recovery ? { recovery_code: code } : { code });
      auth.completeStep(who);
    } catch (err) {
      setError(stepError(err));
      setCode("");
      // Too many wrong codes end this session: back to the password.
      if (err instanceof LiveApiError && (err.status === 429 || err.status === 401)) {
        if (err.code !== "invalid_code") auth.retry();
      }
    } finally {
      setBusy(false);
    }
  }

  const ready = recovery
    ? code.replace(/[^a-z0-9]/gi, "").length >= 10
    : code.replace(/\D/g, "").length === 6;
  return (
    <Shell title={t("auth.steps.mfaTitle")} subtitle={t("auth.steps.mfaSubtitle")}>
      <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
        <Alert text={error} />
        <CodeInput value={code} onChange={setCode} recovery={recovery} />
        <button
          type="submit"
          disabled={busy || !ready}
          className={primary}
          data-testid="step-submit"
        >
          {busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <ShieldCheck className="h-4 w-4" />
          )}
          {t("auth.steps.verify")}
        </button>
        <button
          type="button"
          onClick={() => {
            setRecovery((v) => !v);
            setCode("");
            setError(null);
          }}
          data-testid="step-toggle-recovery"
          className="w-full text-center text-xs text-primary hover:underline"
        >
          {recovery ? t("auth.steps.useApp") : t("auth.steps.useRecovery")}
        </button>
      </form>
    </Shell>
  );
}

export function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = `PrediGol — ${t("auth.steps.recoveryFileTitle")}\n\n${codes.join("\n")}\n`;
  function download() {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "predigol-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(url);
  }
  return (
    <div className="space-y-4" data-testid="recovery-codes">
      <p className="rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-xs text-warning">
        {t("auth.steps.recoveryWarning")}
      </p>
      <ol className="numeric grid grid-cols-2 gap-2 rounded-md border border-border bg-background p-3 text-sm">
        {codes.map((c) => (
          <li key={c} className="text-center font-mono tracking-wider">
            {c}
          </li>
        ))}
      </ol>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={() => {
            void navigator.clipboard?.writeText(codes.join("\n")).then(() => setCopied(true));
          }}
          className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-md border border-border-strong text-xs font-medium hover:bg-elevated"
        >
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? t("auth.steps.copied") : t("auth.steps.copy")}
        </button>
        <button
          type="button"
          onClick={download}
          className="flex h-9 flex-1 items-center justify-center gap-1.5 rounded-md border border-border-strong text-xs font-medium hover:bg-elevated"
        >
          <Download className="h-3.5 w-3.5" />
          {t("auth.steps.download")}
        </button>
      </div>
      <label className="flex items-start gap-2 text-xs">
        <input
          type="checkbox"
          checked={saved}
          onChange={(e) => setSaved(e.target.checked)}
          data-testid="recovery-saved"
          className="mt-0.5"
        />
        <span>{t("auth.steps.recoverySaved")}</span>
      </label>
      <button
        type="button"
        disabled={!saved}
        onClick={onDone}
        className={primary}
        data-testid="recovery-continue"
      >
        {t("auth.steps.continue")}
      </button>
    </div>
  );
}

export function EnrollmentPanel({
  password,
  onEnrolled,
}: {
  /** Asked again when enrolling from a signed-in session. */
  password?: string;
  onEnrolled: (result: { me: Me; recovery_codes: string[] }) => void;
}) {
  const [enrollment, setEnrollment] = useState<MfaEnrollment | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      setEnrollment(await v1.startMfaEnrollment(password));
    } catch (err) {
      setError(stepError(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm(e: FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      onEnrolled(await v1.confirmMfaEnrollment(code));
    } catch (err) {
      setError(stepError(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }

  if (!enrollment) {
    return (
      <div className="space-y-4">
        <Alert text={error} />
        <ol className="list-decimal space-y-1.5 pl-5 text-sm text-muted-foreground">
          <li>{t("auth.steps.enrollStep1")}</li>
          <li>{t("auth.steps.enrollStep2")}</li>
          <li>{t("auth.steps.enrollStep3")}</li>
        </ol>
        <button
          type="button"
          onClick={() => void start()}
          disabled={busy}
          className={primary}
          data-testid="enroll-start"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Smartphone className="h-4 w-4" />}
          {t("auth.steps.enrollStart")}
        </button>
      </div>
    );
  }
  return (
    <form onSubmit={(e) => void confirm(e)} className="space-y-4" noValidate>
      <Alert text={error} />
      <div className="flex flex-col items-center gap-3">
        <img
          src={enrollment.qr_svg}
          alt={t("auth.steps.qrAlt")}
          width={220}
          height={220}
          className="rounded-md bg-white p-2"
          data-testid="enroll-qr"
        />
        <div className="w-full text-center">
          <p className="text-caption text-muted-foreground">{t("auth.steps.manualKey")}</p>
          <p
            className="numeric mt-1 break-all font-mono text-sm tracking-wider"
            data-testid="enroll-secret"
          >
            {enrollment.secret}
          </p>
          <p className="mt-1 text-caption text-subtle-foreground">
            {enrollment.issuer} · {enrollment.account}
          </p>
        </div>
      </div>
      <CodeInput value={code} onChange={setCode} recovery={false} />
      <button
        type="submit"
        disabled={busy || code.replace(/\D/g, "").length !== 6}
        className={primary}
        data-testid="enroll-confirm"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ShieldCheck className="h-4 w-4" />}
        {t("auth.steps.enrollConfirm")}
      </button>
    </form>
  );
}

function EnrollStep() {
  const auth = useAuth();
  const [done, setDone] = useState<{ me: Me; recovery_codes: string[] } | null>(null);
  return (
    <Shell
      title={done ? t("auth.steps.recoveryTitle") : t("auth.steps.enrollTitle")}
      subtitle={done ? t("auth.steps.recoverySubtitle") : t("auth.steps.enrollSubtitle")}
    >
      {done ? (
        <RecoveryCodes codes={done.recovery_codes} onDone={() => auth.completeStep(done.me)} />
      ) : (
        <EnrollmentPanel onEnrolled={setDone} />
      )}
    </Shell>
  );
}

function PasswordStep() {
  const auth = useAuth();
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mismatch = again.length > 0 && next !== again;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || mismatch) return;
    setBusy(true);
    setError(null);
    try {
      auth.completeStep(await v1.setRequiredPassword(next));
    } catch (err) {
      setError(stepError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell title={t("auth.steps.passwordTitle")} subtitle={t("auth.steps.passwordSubtitle")}>
      <form onSubmit={(e) => void submit(e)} className="space-y-4" noValidate>
        <Alert text={error} />
        <label className="block">
          <span className="text-xs font-medium text-muted-foreground">
            {t("profile.newPassword")}
          </span>
          <input
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            data-testid="step-new-password"
            className={field}
          />
        </label>
        <label className="block">
          <span className="text-xs font-medium text-muted-foreground">
            {t("auth.steps.repeatPassword")}
          </span>
          <input
            type="password"
            autoComplete="new-password"
            value={again}
            onChange={(e) => setAgain(e.target.value)}
            data-testid="step-repeat-password"
            className={field}
          />
        </label>
        <p className={cn("text-caption", mismatch ? "text-negative" : "text-subtle-foreground")}>
          {mismatch ? t("auth.steps.passwordMismatch") : t("profile.passwordRules")}
        </p>
        <button
          type="submit"
          disabled={busy || !next || next !== again}
          className={primary}
          data-testid="step-submit"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          {t("auth.steps.savePassword")}
        </button>
      </form>
    </Shell>
  );
}

/** Whatever step this session still owes. */
export function SecurityStep() {
  const auth = useAuth();
  switch (auth.user?.stage) {
    case "mfa":
      return <MfaStep />;
    case "enroll":
      return <EnrollStep />;
    case "password":
      return <PasswordStep />;
    default:
      return null;
  }
}
