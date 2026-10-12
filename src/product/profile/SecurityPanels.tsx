/** My account's security: the second factor, open sessions and recent sign-in activity. */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  History,
  Loader2,
  LogOut,
  MonitorSmartphone,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import type { Me } from "@/lib/api/v1/types_auth";
import { t, translateOr } from "@/lib/i18n";
import { formatDateTime, formatRelative } from "@/lib/time";
import { EnrollmentPanel, RecoveryCodes } from "@/product/auth/SecurityStep";
import { stepError } from "@/product/auth/stepError";
import { deviceLabel } from "./device";
import { cn } from "@/lib/utils";

const field =
  "mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none pointer-coarse:h-11";
const button =
  "tap-y relative inline-flex h-9 items-center gap-2 rounded-md border px-3 text-sm font-medium disabled:opacity-50";

function GuardedForm({
  label,
  danger,
  onSubmit,
  testId,
}: {
  label: string;
  danger?: boolean;
  onSubmit: (password: string, code: string) => Promise<void>;
  testId: string;
}) {
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(password, code);
      setPassword("");
      setCode("");
    } catch (err) {
      setError(stepError(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      onSubmit={(e) => void submit(e)}
      className="grid gap-3 sm:grid-cols-2"
      data-testid={testId}
    >
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("profile.currentPassword")}</span>
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={field}
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("auth.steps.code")}</span>
        <input
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={7}
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))}
          className={cn(field, "numeric tracking-widest")}
        />
      </label>
      {error ? (
        <p role="alert" className="text-xs text-negative sm:col-span-2">
          {error}
        </p>
      ) : null}
      <div className="sm:col-span-2">
        <button
          type="submit"
          disabled={busy || !password || code.replace(/\D/g, "").length !== 6}
          className={cn(
            button,
            danger
              ? "border-negative/40 text-negative hover:bg-negative-soft"
              : "border-border-strong hover:bg-elevated",
          )}
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
          {label}
        </button>
      </div>
    </form>
  );
}

export function TwoFactorPanel({ user }: { user: Me }) {
  const auth = useAuth();
  const [mode, setMode] = useState<"idle" | "enroll" | "codes" | "disable">("idle");
  const [password, setPassword] = useState("");
  const [passwordOk, setPasswordOk] = useState(false);
  const [codes, setCodes] = useState<{ codes: string[]; me: Me | null } | null>(null);

  if (codes) {
    return (
      <RecoveryCodes
        codes={codes.codes}
        onDone={() => {
          if (codes.me) auth.completeStep(codes.me);
          else auth.retry();
          setCodes(null);
          setMode("idle");
        }}
      />
    );
  }
  return (
    <div className="space-y-3" data-testid="two-factor-panel">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {user.mfa_enabled ? (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-positive/40 bg-positive-soft px-2 py-0.5 text-xs font-semibold text-positive">
            <ShieldCheck aria-hidden className="h-3.5 w-3.5" />
            {t("profile.securityPanel.mfaOn")}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border-strong px-2 py-0.5 text-xs font-semibold text-muted-foreground">
            <ShieldOff aria-hidden className="h-3.5 w-3.5" />
            {t("profile.securityPanel.mfaOff")}
          </span>
        )}
        {user.mfa_required ? (
          <span className="text-caption text-gold">{t("profile.securityPanel.mfaRequired")}</span>
        ) : null}
        {user.mfa_enabled ? (
          <span
            className={cn(
              "text-caption",
              user.recovery_codes_left <= 2 ? "text-warning" : "text-muted-foreground",
            )}
          >
            {t("profile.securityPanel.codesLeft", { count: user.recovery_codes_left })}
          </span>
        ) : null}
      </div>
      <p className="text-xs text-muted-foreground">{t("profile.securityPanel.mfaHelp")}</p>

      {!user.mfa_enabled && mode === "idle" ? (
        <button
          type="button"
          onClick={() => setMode("enroll")}
          data-testid="mfa-enable"
          className={cn(button, "border-primary/50 text-primary hover:bg-primary/10")}
        >
          <ShieldCheck aria-hidden className="h-4 w-4" />
          {t("profile.securityPanel.enable")}
        </button>
      ) : null}
      {mode === "enroll" && !passwordOk ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setPasswordOk(true);
          }}
          className="flex flex-wrap items-end gap-2"
        >
          <label className="block min-w-48 flex-1">
            <span className="text-xs text-muted-foreground">{t("profile.currentPassword")}</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={field}
            />
          </label>
          <button
            type="submit"
            disabled={!password}
            className={cn(button, "border-border-strong hover:bg-elevated")}
          >
            {t("auth.steps.continue")}
          </button>
        </form>
      ) : null}
      {mode === "enroll" && passwordOk ? (
        <EnrollmentPanel
          password={password}
          onEnrolled={(r) => {
            setPassword("");
            setPasswordOk(false);
            setCodes({ codes: r.recovery_codes, me: r.me });
          }}
        />
      ) : null}

      {user.mfa_enabled && mode === "idle" ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setMode("codes")}
            className={cn(button, "border-border-strong hover:bg-elevated")}
          >
            <RefreshCw aria-hidden className="h-4 w-4" />
            {t("profile.securityPanel.newCodes")}
          </button>
          {!user.mfa_required ? (
            <button
              type="button"
              onClick={() => setMode("disable")}
              className={cn(button, "border-negative/40 text-negative hover:bg-negative-soft")}
            >
              <ShieldOff aria-hidden className="h-4 w-4" />
              {t("profile.securityPanel.disable")}
            </button>
          ) : null}
        </div>
      ) : null}
      {mode === "codes" ? (
        <GuardedForm
          testId="mfa-new-codes"
          label={t("profile.securityPanel.newCodes")}
          onSubmit={async (pw, code) => {
            const r = await v1.renewRecoveryCodes(pw, code);
            setCodes({ codes: r.recovery_codes, me: null });
          }}
        />
      ) : null}
      {mode === "disable" ? (
        <GuardedForm
          testId="mfa-disable"
          danger
          label={t("profile.securityPanel.disable")}
          onSubmit={async (pw, code) => {
            await v1.disableMfa(pw, code);
            setMode("idle");
            auth.retry();
          }}
        />
      ) : null}
      {mode !== "idle" ? (
        <button
          type="button"
          onClick={() => {
            setMode("idle");
            setPassword("");
            setPasswordOk(false);
          }}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          {t("common.cancel")}
        </button>
      ) : null}
    </div>
  );
}

export function SessionsPanel() {
  const qc = useQueryClient();
  const sessions = useQuery({ queryKey: ["auth", "sessions"], queryFn: v1.mySessions });
  const refresh = () => void qc.invalidateQueries({ queryKey: ["auth", "sessions"] });
  const revoke = useMutation({
    mutationFn: (id: string) => v1.revokeMySession(id),
    onSuccess: refresh,
  });
  const others = useMutation({ mutationFn: () => v1.revokeMyOtherSessions(), onSuccess: refresh });
  const list = sessions.data ?? [];
  return (
    <div className="space-y-3" data-testid="sessions-panel">
      {sessions.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : (
        <ul className="divide-y divide-border/70 rounded-md border border-border">
          {list.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 px-3 py-2.5 text-sm">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 font-medium">
                  <MonitorSmartphone
                    aria-hidden
                    className="h-4 w-4 shrink-0 text-muted-foreground"
                  />
                  <span className="truncate">{deviceLabel(s.user_agent)}</span>
                  {s.current ? (
                    <span className="rounded-full bg-primary/10 px-1.5 py-0.5 text-[0.65rem] font-bold text-primary">
                      {t("profile.securityPanel.thisDevice")}
                    </span>
                  ) : null}
                </div>
                <div className="numeric text-caption text-muted-foreground">
                  {s.ip ?? "—"} · {t("profile.securityPanel.lastSeen")}{" "}
                  {formatRelative(s.last_seen_at)}
                </div>
              </div>
              {!s.current ? (
                <button
                  type="button"
                  onClick={() => revoke.mutate(s.id)}
                  disabled={revoke.isPending}
                  className="tap-y relative shrink-0 rounded-md border border-border-strong px-2 py-1 text-xs hover:bg-elevated pointer-coarse:px-3 pointer-coarse:py-2"
                >
                  {t("profile.securityPanel.end")}
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {list.length > 1 ? (
        <button
          type="button"
          onClick={() => others.mutate()}
          disabled={others.isPending}
          data-testid="sessions-end-others"
          className={cn(button, "border-negative/40 text-negative hover:bg-negative-soft")}
        >
          <LogOut aria-hidden className="h-4 w-4" />
          {t("profile.securityPanel.endOthers")}
        </button>
      ) : null}
    </div>
  );
}

export function AccessPanel() {
  const access = useQuery({ queryKey: ["auth", "access"], queryFn: () => v1.myAccess(20) });
  const rows = access.data ?? [];
  return (
    <div data-testid="access-panel">
      {access.isPending ? (
        <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
      ) : rows.length === 0 ? (
        <p className="text-xs text-muted-foreground">{t("profile.securityPanel.noActivity")}</p>
      ) : (
        <ul className="space-y-1.5 text-xs">
          {rows.map((r, i) => {
            const bad =
              r.action.endsWith("failed") ||
              r.action.endsWith("locked") ||
              r.action === "login.refused";
            return (
              <li key={`${r.at}-${i}`} className="flex items-start gap-2">
                <History
                  aria-hidden
                  className={cn(
                    "mt-0.5 h-3.5 w-3.5 shrink-0",
                    bad ? "text-negative" : "text-muted-foreground",
                  )}
                />
                <span className="min-w-0">
                  <span className={cn("font-medium", bad && "text-negative")}>
                    {translateOr(`profile.securityPanel.action.${r.action}`, r.action)}
                  </span>{" "}
                  <span className="numeric text-muted-foreground">
                    {formatDateTime(r.at)} · {r.ip ?? "—"}
                    {r.user_agent ? ` · ${deviceLabel(r.user_agent)}` : ""}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
