/**
 * The account centre's Cuenta (plan UX, B1; section 21): the alias the reader chooses (PATCH /auth/me/preferences, 1 to
 * 80 characters), the address, the account's state in words, since when it exists and how long a session lasts. The
 * address cannot be changed here (there is no such flow); the owner's account says «Administrador», a reader's never a
 * role.
 */
import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import type { Me } from "@/lib/api/v1/types_auth";
import type { AccountSummary } from "@/lib/api/v1/types_account";
import { t } from "@/lib/i18n";
import { fmtInt } from "@/lib/i18n/format";
import { formatDateLong, formatDateTime } from "@/lib/time";
import { errorMessage } from "@/product/shared/States";
import { ALIAS_MAX, accountState, aliasProblem } from "./centre";

/** "7 días", "8 horas": how long a session may go unused. */
function idleText(hours: number): string {
  return hours % 24 === 0
    ? t("profile.idleDays", { count: hours / 24, n: fmtInt(hours / 24) })
    : t("profile.idleHours", { count: hours, n: fmtInt(hours) });
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border/70 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-sm">{children}</span>
    </div>
  );
}

function AliasForm({ user }: { user: Me }) {
  const auth = useAuth();
  const qc = useQueryClient();
  const [value, setValue] = useState(user.display_name);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const problem = aliasProblem(value);
  const changed = value.trim() !== user.display_name;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (problem || !changed || busy) return;
    setBusy(true);
    setMessage(null);
    try {
      const who = await auth.updatePreferences({ display_name: value.trim() });
      setValue(who.display_name);
      setMessage({ ok: true, text: t("profile.centre.alias.saved") });
      void qc.invalidateQueries({ queryKey: ["me", "account"] });
    } catch (err) {
      setMessage({ ok: false, text: errorMessage(err) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-2" data-testid="alias-form">
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("profile.centre.alias.label")}</span>
        <input
          type="text"
          value={value}
          maxLength={ALIAS_MAX + 20}
          autoComplete="nickname"
          onChange={(e) => {
            setValue(e.target.value);
            setMessage(null);
          }}
          aria-describedby="alias-help"
          aria-invalid={problem ? true : undefined}
          data-testid="alias-input"
          className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none sm:text-sm"
        />
      </label>
      <p id="alias-help" className="text-caption text-subtle-foreground">
        {problem === "long"
          ? t("profile.centre.alias.long", { max: ALIAS_MAX })
          : problem === "empty"
            ? t("profile.centre.alias.empty")
            : t("profile.centre.alias.help")}
      </p>
      {message ? (
        <p
          role={message.ok ? "status" : "alert"}
          className={message.ok ? "text-xs text-positive" : "text-xs text-negative"}
          data-testid="alias-message"
        >
          {message.text}
        </p>
      ) : null}
      <button
        type="submit"
        disabled={busy || Boolean(problem) || !changed}
        data-testid="alias-save"
        className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50"
      >
        {busy ? (
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
        ) : (
          <Check aria-hidden className="h-4 w-4" />
        )}
        {t("profile.centre.alias.save")}
      </button>
    </form>
  );
}

export function AccountPanel({ user, summary }: { user: Me; summary: AccountSummary | undefined }) {
  const admin = user.role === "SUPER_ADMIN";
  return (
    <div className="space-y-4" data-testid="account-panel">
      <AliasForm user={user} />
      <div>
        <Row label={t("profile.email")}>
          <span data-testid="account-email-shown">{user.email}</span>
        </Row>
        {admin ? (
          // plan UX, A1 (F07): the owner's account says «Administrador»; a reader never sees a role
          <Row label={t("profile.role")}>
            <span
              className="rounded-full border border-gold/40 bg-gold-soft px-2 py-0.5 text-xs font-bold tracking-wider text-gold-strong"
              data-testid="profile-role"
            >
              {t("common.roleAdmin")}
            </span>
          </Row>
        ) : (
          <Row label={t("profile.centre.stateLabel")}>
            <span data-testid="account-state">{accountState(false, user.membership ?? null)}</span>
          </Row>
        )}
        {summary?.account.created_at ? (
          <Row label={t("profile.centre.sinceLabel")}>
            <span data-testid="account-since">
              {t("profile.centre.since", { date: formatDateLong(summary.account.created_at) })}
            </span>
          </Row>
        ) : null}
        <Row label={t("profile.sessionLabel")}>
          {/* The session slides with use (plan UX, A1): open until this date at most, sooner if it goes unused. */}
          <span className="text-xs" data-testid="profile-session">
            {t("profile.sessionUntil", { date: formatDateTime(user.session_expires_at) })}
            {user.session_idle_hours ? (
              <span className="block text-caption text-muted-foreground">
                {t("profile.sessionIdle", { idle: idleText(user.session_idle_hours) })}
              </span>
            ) : null}
          </span>
        </Row>
      </div>
    </div>
  );
}
