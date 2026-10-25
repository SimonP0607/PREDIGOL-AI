/**
 * Accounts: who can sign in, with which role. SUPER_ADMIN only (enforced by the API). From A7 (plan UX), an account is
 * opened by an invitation - an e-mail with a one-use link - while self-service is on; the temporary password stays as
 * the backup. An account is deleted only as anonymisation, its address typed again; the deleted ones hide by default.
 */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Copy,
  KeyRound,
  Loader2,
  Lock,
  LogOut,
  Mail,
  Plus,
  RefreshCw,
  Send,
  ShieldCheck,
  ShieldOff,
  Unlock,
  UserRound,
  Wand2,
} from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { useAuth } from "@/lib/auth/AuthProvider";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type {
  AdminInviteIn,
  AdminUser,
  AdminUserCreate,
  Language,
  RoleKey,
} from "@/lib/api/v1/types_auth";
import { t } from "@/lib/i18n";
import { detectTimeZone, formatDateTime, formatRelative, listTimeZones } from "@/lib/time";
import { Card, ErrorState, SkeletonCards, errorMessage } from "@/product/shared/States";
import { cn } from "@/lib/utils";
import { AnonymiseAccount } from "./AnonymiseAccount";
import { MembershipCell } from "./MembershipCell";
import { anonymisedSummary } from "./anonymised";
import { PrivacyRequestsCard } from "./PrivacyRequests";

const ROLES: RoleKey[] = ["USER", "SUPER_ADMIN"];
const DUE_STATES: readonly string[] = ["expiring", "grace", "expired"];

function RoleBadge({ role }: { role: string }) {
  const admin = role === "SUPER_ADMIN";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.65rem] font-bold tracking-wider",
        admin
          ? "border-gold/45 bg-gold-soft text-gold-strong"
          : "border-border-strong text-muted-foreground",
      )}
    >
      {admin ? (
        <ShieldCheck aria-hidden className="h-3 w-3" />
      ) : (
        <UserRound aria-hidden className="h-3 w-3" />
      )}
      {role}
    </span>
  );
}

function StatusDot({ status }: { status: AdminUser["status"] }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span
        aria-hidden
        className={cn(
          "h-2 w-2 rounded-full",
          status === "active"
            ? "bg-positive"
            : status === "invited"
              ? "bg-warning"
              : status === "deleted"
                ? "bg-subtle-foreground"
                : "bg-negative",
        )}
      />
      {t(`admin.users.${status}`)}
    </span>
  );
}

function generated(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789-_.!@#%+=";
  const bytes = new Uint32Array(18);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
}

const field =
  "mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none";

/** «Invitar» (plan UX, A7): address, alias, language and time zone; the e-mail carries the one-use link. */
function InviteForm({
  emailSending,
  onDone,
}: {
  emailSending: boolean;
  onDone: (notice: string) => void;
}) {
  const qc = useQueryClient();
  const [form, setForm] = useState<AdminInviteIn>({
    email: "",
    display_name: "",
    language: "es",
    timezone: "America/Bogota",
  });
  const [error, setError] = useState<string | null>(null);
  const invite = useMutation({
    mutationFn: (body: AdminInviteIn) => v1.inviteUser(body),
    onSuccess: (r) => {
      void qc.invalidateQueries({ queryKey: live.users.queryKey });
      const sent = t("admin.users.invitedOk", { email: r.data.email });
      onDone(emailSending ? sent : `${sent} ${t("admin.users.emailSendingOff")}`);
    },
    onError: (err) => setError(errorMessage(err)),
  });
  const zones = listTimeZones();
  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body: AdminInviteIn = { ...form, email: form.email.trim() };
    if (!body.display_name?.trim()) delete body.display_name;
    invite.mutate(body);
  }
  return (
    <form onSubmit={submit} className="space-y-3 p-4" data-testid="invite-form">
      <div>
        <h2 className="font-display text-base font-semibold">{t("admin.users.inviteTitle")}</h2>
        <p className="mt-1 text-xs text-muted-foreground">{t("admin.users.inviteHelp")}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("admin.users.email")}</span>
          <input
            type="email"
            required
            autoComplete="off"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            className={field}
            data-testid="invite-email"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("admin.users.alias")}</span>
          <input
            value={form.display_name ?? ""}
            maxLength={80}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            className={field}
            data-testid="invite-alias"
          />
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("admin.users.language")}</span>
          <select
            value={form.language}
            onChange={(e) => setForm({ ...form, language: e.target.value as Language })}
            className={field}
            data-testid="invite-language"
          >
            <option value="es">Español</option>
            <option value="en">English</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("admin.users.timezone")}</span>
          <select
            value={form.timezone}
            onChange={(e) => setForm({ ...form, timezone: e.target.value })}
            className={field}
            data-testid="invite-timezone"
          >
            {zones.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-xs text-muted-foreground">{t("admin.membership.inviteTrial")}</span>
          <select
            value={form.trial_days ?? ""}
            onChange={(e) => {
              const days = e.target.value ? Number(e.target.value) : undefined;
              const next: AdminInviteIn = { ...form };
              if (days === undefined) delete next.trial_days;
              else next.trial_days = days;
              setForm(next);
            }}
            className={field}
            data-testid="invite-trial"
          >
            <option value="">{t("admin.membership.inviteTrialDefault")}</option>
            {[7, 8, 9, 10, 11, 12, 13, 14].map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-negative">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={invite.isPending || !form.email.trim()}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          data-testid="invite-submit"
        >
          {invite.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Send className="h-4 w-4" />
          )}
          {invite.isPending ? t("admin.users.sending") : t("admin.users.sendInvite")}
        </button>
      </div>
    </form>
  );
}

function CreateForm({ onDone, backup }: { onDone: () => void; backup: boolean }) {
  const qc = useQueryClient();
  const [form, setForm] = useState<AdminUserCreate>({
    email: "",
    display_name: "",
    role: "USER",
    password: generated(),
    language: "es",
    timezone: detectTimeZone(),
    must_change_password: true,
    mfa_required: false,
  });
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: (body: AdminUserCreate) => v1.createUser(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: live.users.queryKey });
      onDone();
    },
    onError: (err) => {
      const problems =
        err instanceof LiveApiError ? err.problems.map((p) => t(`errors.problem.${p}`)) : [];
      setError([errorMessage(err), ...problems].join(" "));
    },
  });
  const zones = listTimeZones();
  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    const body: AdminUserCreate = { ...form };
    if (!body.display_name) delete body.display_name;
    create.mutate(body);
  }
  return (
    <form
      onSubmit={submit}
      className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="create-user-form"
    >
      {backup ? (
        <p className="text-xs text-muted-foreground sm:col-span-2 lg:col-span-3">
          {t("admin.users.temporaryBackupHelp")}
        </p>
      ) : null}
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.users.email")}</span>
        <input
          type="email"
          required
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          className={field}
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.users.user")}</span>
        <input
          value={form.display_name ?? ""}
          onChange={(e) => setForm({ ...form, display_name: e.target.value })}
          className={field}
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.users.role")}</span>
        <select
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value as RoleKey })}
          className={field}
        >
          {ROLES.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.users.language")}</span>
        <select
          value={form.language}
          onChange={(e) => setForm({ ...form, language: e.target.value as Language })}
          className={field}
        >
          <option value="es">Español</option>
          <option value="en">English</option>
        </select>
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.users.timezone")}</span>
        <select
          value={form.timezone}
          onChange={(e) => setForm({ ...form, timezone: e.target.value })}
          className={field}
        >
          {zones.map((z) => (
            <option key={z} value={z}>
              {z}
            </option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("admin.users.initialPassword")}</span>
        <span className="mt-1 flex gap-1.5">
          <input
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            className={cn(field, "mt-0 numeric")}
            autoComplete="off"
          />
          <button
            type="button"
            aria-label="generate"
            onClick={() => setForm({ ...form, password: generated() })}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border-strong hover:bg-elevated"
          >
            <Wand2 aria-hidden className="h-4 w-4" />
          </button>
        </span>
        <span className="mt-1 block text-caption text-subtle-foreground">
          {t("admin.users.passwordHint")}
        </span>
      </label>
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs sm:col-span-2 lg:col-span-3">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.must_change_password ?? true}
            onChange={(e) => setForm({ ...form, must_change_password: e.target.checked })}
            data-testid="create-must-change"
          />
          {t("admin.users.mustChangeOnCreate")}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.role === "SUPER_ADMIN" || (form.mfa_required ?? false)}
            disabled={form.role === "SUPER_ADMIN"}
            onChange={(e) => setForm({ ...form, mfa_required: e.target.checked })}
            data-testid="create-mfa-required"
          />
          {t("admin.users.requireMfa")}
          {form.role === "SUPER_ADMIN" ? (
            <span className="text-subtle-foreground">({t("admin.users.mfaByRole")})</span>
          ) : null}
        </label>
      </div>
      {error ? (
        <p role="alert" className="text-xs text-negative sm:col-span-2 lg:col-span-3">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2 sm:col-span-2 lg:col-span-3">
        <button
          type="submit"
          disabled={create.isPending || !form.email}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          {create.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Plus className="h-4 w-4" />
          )}
          {create.isPending ? t("admin.users.creating") : t("admin.users.create")}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="h-9 rounded-md border border-border-strong px-3 text-sm hover:bg-elevated"
        >
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

function RowActions({
  user,
  self,
  onNotice,
}: {
  user: AdminUser;
  self: boolean;
  onNotice: (notice: string) => void;
}) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<"status" | "role" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [resent, setResent] = useState(false);
  const resend = useMutation({
    mutationFn: () => v1.resendInvitation(user.id),
    onSuccess: () => {
      setError(null);
      setResent(true);
      void qc.invalidateQueries({ queryKey: live.users.queryKey });
    },
    onError: (err) => setError(errorMessage(err)),
  });
  const update = useMutation({
    mutationFn: (body: { role?: string; status?: "active" | "disabled" }) =>
      v1.updateUser(user.id, body),
    onSuccess: () => {
      setConfirm(null);
      setError(null);
      void qc.invalidateQueries({ queryKey: live.users.queryKey });
    },
    onError: (err) => setError(errorMessage(err)),
  });
  const nextStatus = user.status === "active" ? "disabled" : "active";
  const nextRole = user.role === "SUPER_ADMIN" ? "USER" : "SUPER_ADMIN";
  // Touch: taller, with a 44 px reach (tap-y) and a 10 px gap between wrapped rows so reaches never overlap.
  const btn =
    "tap-y relative rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-50 pointer-coarse:px-2.5 pointer-coarse:py-2";
  // Nothing about a deleted account changes any more.
  if (user.status === "deleted")
    return <span className="text-caption text-subtle-foreground">—</span>;
  const deletable = !self && user.role !== "SUPER_ADMIN";
  const remove = deletable ? (
    <AnonymiseAccount
      userId={user.id}
      email={user.email}
      invited={user.status === "invited"}
      onDone={(r) => onNotice(anonymisedSummary(r))}
    />
  ) : null;
  // An invitation nobody used yet: a new link (the previous one stops working), or withdrawing it.
  if (user.status === "invited") {
    return (
      <div className="flex flex-col items-start gap-1">
        <div className="flex flex-wrap gap-1.5 pointer-coarse:gap-2.5">
          <button
            type="button"
            data-testid={`resend-${user.id}`}
            disabled={resend.isPending}
            onClick={() => resend.mutate()}
            className={cn(
              btn,
              "inline-flex items-center gap-1 border-border-strong hover:bg-elevated",
            )}
          >
            <Mail aria-hidden className="h-3 w-3" />
            {t("admin.users.resendInvite")}
          </button>
          {remove}
        </div>
        {resent ? (
          <span className="text-caption text-positive" data-testid={`resent-${user.id}`}>
            {t("admin.users.inviteResent")}
          </span>
        ) : null}
        {error ? (
          <span role="alert" className="text-caption text-negative">
            {error}
          </span>
        ) : null}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap gap-1.5 pointer-coarse:gap-2.5">
        {confirm === "status" ? (
          <button
            type="button"
            data-testid={`confirm-status-${user.id}`}
            disabled={update.isPending}
            onClick={() => update.mutate({ status: nextStatus })}
            className={cn(btn, "border-negative/50 bg-negative-soft text-negative")}
          >
            {t("common.confirm")} ·{" "}
            {nextStatus === "disabled" ? t("admin.users.deactivate") : t("admin.users.activate")}
          </button>
        ) : (
          <button
            type="button"
            data-testid={`status-${user.id}`}
            disabled={self || update.isPending}
            onClick={() => setConfirm("status")}
            className={cn(btn, "border-border-strong hover:bg-elevated")}
          >
            {nextStatus === "disabled" ? t("admin.users.deactivate") : t("admin.users.activate")}
          </button>
        )}
        {confirm === "role" ? (
          <button
            type="button"
            data-testid={`confirm-role-${user.id}`}
            disabled={update.isPending}
            onClick={() => update.mutate({ role: nextRole })}
            className={cn(btn, "border-gold/50 bg-gold-soft text-gold-strong")}
          >
            {t("common.confirm")} · {nextRole}
          </button>
        ) : (
          <button
            type="button"
            data-testid={`role-${user.id}`}
            disabled={update.isPending}
            onClick={() => setConfirm("role")}
            className={cn(btn, "border-border-strong hover:bg-elevated")}
          >
            {nextRole === "SUPER_ADMIN" ? t("admin.users.makeAdmin") : t("admin.users.makeUser")}
          </button>
        )}
        {confirm ? (
          <button
            type="button"
            onClick={() => setConfirm(null)}
            className={cn(btn, "border-transparent text-muted-foreground")}
          >
            {t("common.cancel")}
          </button>
        ) : null}
        {confirm ? null : remove}
      </div>
      {error ? (
        <span role="alert" className="text-caption text-negative">
          {error}
        </span>
      ) : null}
    </div>
  );
}

function SecurityBadges({ user }: { user: AdminUser }) {
  const chip =
    "inline-flex items-center gap-1 rounded-full border px-1.5 py-0.5 text-[0.65rem] font-semibold";
  return (
    <div className="flex flex-wrap gap-1" data-testid={`security-${user.id}`}>
      {user.mfa_enabled ? (
        <span className={cn(chip, "border-positive/40 text-positive")}>
          <ShieldCheck aria-hidden className="h-3 w-3" />
          2FA
        </span>
      ) : user.mfa_required ? (
        <span className={cn(chip, "border-warning/50 text-warning")}>
          <ShieldOff aria-hidden className="h-3 w-3" />
          {t("admin.users.mfaPending")}
        </span>
      ) : (
        <span className={cn(chip, "border-border-strong text-muted-foreground")}>
          {t("admin.users.mfaOff")}
        </span>
      )}
      {user.locked_until ? (
        <span className={cn(chip, "border-negative/50 text-negative")}>
          <Lock aria-hidden className="h-3 w-3" />
          {t("admin.users.locked")}
        </span>
      ) : null}
      {user.must_change_password ? (
        <span className={cn(chip, "border-gold/45 text-gold-strong")}>
          <KeyRound aria-hidden className="h-3 w-3" />
          {t("admin.users.mustChange")}
        </span>
      ) : null}
    </div>
  );
}

type SecurityAction = "password" | "mfa" | "sessions" | "unlock" | "requireMfa";

function SecurityActions({ user, self }: { user: AdminUser; self: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<SecurityAction | null>(null);
  const [temporary, setTemporary] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: async (action: SecurityAction): Promise<string | null> => {
      switch (action) {
        case "password": {
          const r = await v1.resetUserPassword(user.id);
          setTemporary(r.data?.temporary_password ?? null);
          return null;
        }
        case "mfa":
          await v1.resetUserMfa(user.id);
          return t("admin.users.mfaResetDone");
        case "sessions": {
          const r = await v1.revokeUserSessions(user.id);
          return t("admin.users.sessionsEnded", { count: r.data?.revoked ?? 0 });
        }
        case "unlock":
          await v1.unlockUser(user.id);
          return t("admin.users.unlocked");
        case "requireMfa":
          await v1.updateUser(user.id, { mfa_required: !user.mfa_required });
          return null;
      }
    },
    onSuccess: (msg) => {
      setConfirm(null);
      setError(null);
      setNotice(msg);
      void qc.invalidateQueries({ queryKey: live.users.queryKey });
    },
    onError: (err) => setError(errorMessage(err)),
  });
  // Touch: taller, with a 44 px reach (tap-y) and a 10 px gap between wrapped rows so reaches never overlap.
  const btn =
    "tap-y relative rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-50 pointer-coarse:px-2.5 pointer-coarse:py-2";
  const invited = user.status === "invited";
  const labels: Record<SecurityAction, string> = {
    password: invited ? t("admin.users.temporaryBackup") : t("admin.users.resetPassword"),
    mfa: t("admin.users.resetMfa"),
    sessions: t("admin.users.endSessions"),
    unlock: t("admin.users.unlock"),
    requireMfa: user.mfa_required
      ? t("admin.users.dropMfaRequirement")
      : t("admin.users.requireMfa"),
  };
  const available: SecurityAction[] =
    user.status === "deleted"
      ? []
      : invited
        ? ["password"]
        : [
            "password",
            ...(user.mfa_enabled ? (["mfa"] as const) : []),
            ...(user.active_sessions > 0 && !self ? (["sessions"] as const) : []),
            ...(user.locked_until ? (["unlock"] as const) : []),
            ...(user.role !== "SUPER_ADMIN" ? (["requireMfa"] as const) : []),
          ];
  if (available.length === 0) return null;
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap gap-1.5 pointer-coarse:gap-2.5">
        {available.map((a) =>
          confirm === a ? (
            <button
              key={a}
              type="button"
              disabled={act.isPending}
              onClick={() => act.mutate(a)}
              data-testid={`confirm-${a}-${user.id}`}
              className={cn(btn, "border-negative/50 bg-negative-soft text-negative")}
            >
              {t("common.confirm")} · {labels[a]}
            </button>
          ) : (
            <button
              key={a}
              type="button"
              disabled={act.isPending || (self && a !== "requireMfa" && a !== "password")}
              onClick={() => {
                setNotice(null);
                setTemporary(null);
                setConfirm(a);
              }}
              data-testid={`${a}-${user.id}`}
              className={cn(btn, "border-border-strong hover:bg-elevated")}
            >
              {a === "unlock" ? <Unlock aria-hidden className="mr-1 inline h-3 w-3" /> : null}
              {a === "sessions" ? <LogOut aria-hidden className="mr-1 inline h-3 w-3" /> : null}
              {labels[a]}
            </button>
          ),
        )}
        {confirm ? (
          <button
            type="button"
            onClick={() => setConfirm(null)}
            className={cn(btn, "border-transparent text-muted-foreground")}
          >
            {t("common.cancel")}
          </button>
        ) : null}
      </div>
      {temporary ? (
        <div
          className="mt-1 rounded-md border border-gold/45 bg-gold-soft p-2 text-xs"
          data-testid={`temporary-password-${user.id}`}
        >
          <div className="text-gold-strong">{t("admin.users.temporaryPassword")}</div>
          <div className="mt-1 flex items-center gap-2">
            <code className="numeric font-mono text-sm tracking-wider">{temporary}</code>
            <button
              type="button"
              aria-label={t("auth.steps.copy")}
              onClick={() => void navigator.clipboard?.writeText(temporary)}
              className="rounded border border-border-strong p-1 hover:bg-elevated"
            >
              <Copy aria-hidden className="h-3 w-3" />
            </button>
          </div>
          <div className="mt-1 text-caption text-muted-foreground">
            {t("admin.users.temporaryHint")}
          </div>
        </div>
      ) : null}
      {notice ? <span className="text-caption text-positive">{notice}</span> : null}
      {error ? (
        <span role="alert" className="text-caption text-negative">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export function UsersPage() {
  const auth = useAuth();
  const q = useQuery({ ...live.users });
  const options = useQuery({
    queryKey: ["admin", "self-service"],
    queryFn: v1.selfServiceState,
    staleTime: 60_000,
  });
  const selfService = options.data?.self_service ?? false;
  const [creating, setCreating] = useState<"invite" | "password" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [showDeleted, setShowDeleted] = useState(false);
  // The owner's morning notice links here with ?membership=due (plan UX, A8): the accounts ending, in grace or ended.
  const [dueOnly, setDueOnly] = useState(() => {
    try {
      return new URLSearchParams(window.location.search).get("membership") === "due";
    } catch {
      return false;
    }
  });
  const everyone = q.data?.data ?? [];
  const deleted = everyone.filter((u) => u.status === "deleted").length;
  const visible = showDeleted ? everyone : everyone.filter((u) => u.status !== "deleted");
  const users = dueOnly
    ? visible.filter((u) => DUE_STATES.includes(u.membership?.state ?? "none"))
    : visible;
  const toggle = (form: "invite" | "password") => {
    setNotice(null);
    setCreating((v) => (v === form ? null : form));
  };
  return (
    <div className="space-y-5">
      <PageHeader
        title={t("admin.pages.users.title")}
        description={t("admin.pages.users.description")}
        actions={
          <>
            <button
              type="button"
              onClick={() => void q.refetch()}
              aria-label={t("common.retry")}
              className="tap relative rounded-md border border-border-strong p-2 hover:bg-elevated"
            >
              <RefreshCw aria-hidden className={cn("h-4 w-4", q.isFetching && "animate-spin")} />
            </button>
            {selfService ? (
              <button
                type="button"
                data-testid="invite-user"
                onClick={() => toggle("invite")}
                className="tap-y relative inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground"
              >
                <Send aria-hidden className="h-4 w-4" />
                {t("admin.users.invite")}
              </button>
            ) : null}
            <button
              type="button"
              data-testid="new-user"
              onClick={() => toggle("password")}
              className={cn(
                "tap-y relative inline-flex h-9 items-center gap-2 rounded-md px-3 text-sm font-semibold",
                selfService
                  ? "border border-border-strong hover:bg-elevated"
                  : "bg-primary text-primary-foreground",
              )}
            >
              <Plus aria-hidden className="h-4 w-4" />
              {selfService ? t("admin.users.temporaryBackup") : t("admin.users.newUser")}
            </button>
          </>
        }
      />
      {options.data && !selfService ? (
        <p className="text-xs text-muted-foreground" data-testid="self-service-off">
          {t("admin.users.selfServiceOff")}
        </p>
      ) : null}
      {notice ? (
        <p
          role="status"
          className="rounded-md border border-positive/40 bg-positive/10 px-3 py-2 text-sm text-positive"
          data-testid="users-notice"
        >
          {notice}
        </p>
      ) : null}
      {creating === "invite" ? (
        <Card>
          <InviteForm
            emailSending={options.data?.email_sending ?? false}
            onDone={(msg) => {
              setCreating(null);
              setNotice(msg);
            }}
          />
        </Card>
      ) : creating === "password" ? (
        <Card>
          <CreateForm onDone={() => setCreating(null)} backup={selfService} />
        </Card>
      ) : null}
      <Card className="overflow-hidden">
        {q.isPending ? (
          <SkeletonCards className="p-4" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2 text-caption text-muted-foreground">
              <span>
                {dueOnly ? `${t("admin.membership.dueFilterOn")} · ` : ""}
                {t("admin.users.count", { count: users.length })}
              </span>
              <button
                type="button"
                onClick={() => setDueOnly((v) => !v)}
                className="tap-y relative text-caption font-medium text-primary"
                data-testid="membership-due-filter"
              >
                {dueOnly ? t("admin.membership.showAll") : t("admin.membership.dueFilter")}
              </button>
              {deleted > 0 ? (
                <button
                  type="button"
                  onClick={() => setShowDeleted((v) => !v)}
                  className="tap-y relative text-caption font-medium text-primary"
                  data-testid="show-deleted"
                >
                  {showDeleted
                    ? t("admin.users.hideDeleted")
                    : t("admin.users.showDeleted", { count: deleted })}
                </button>
              ) : null}
            </div>
            {/* The table from xl only: on a tablet (768-1279 px) its actions column sat off-screen and every row
                was a tower of buttons; there each account is a card with its actions in reach. */}
            <div className="hidden overflow-x-auto xl:block">
              <table className="w-full text-sm" data-testid="users-table">
                <thead className="text-left text-caption uppercase tracking-wider text-subtle-foreground">
                  <tr className="border-b border-border">
                    <th className="px-4 py-2 font-medium">{t("admin.users.user")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.role")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.status")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.security")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.membership.column")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.language")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.timezone")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.created")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.lastLogin")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.actions")}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => (
                    <tr
                      key={u.id}
                      className="border-b border-border/60 align-top last:border-0"
                      data-testid={`user-row-${u.id}`}
                    >
                      <td className="px-4 py-3">
                        <div className="font-medium">
                          {u.display_name}
                          {u.id === auth.user?.id ? (
                            <span className="ml-1.5 text-caption text-gold">
                              ({t("admin.users.you")})
                            </span>
                          ) : null}
                        </div>
                        <div className="text-caption text-muted-foreground">{u.email}</div>
                      </td>
                      <td className="px-3 py-3">
                        <RoleBadge role={u.role} />
                      </td>
                      <td className="px-3 py-3">
                        <StatusDot status={u.status} />
                      </td>
                      <td className="px-3 py-3">
                        <SecurityBadges user={u} />
                      </td>
                      <td className="px-3 py-3">
                        <MembershipCell user={u} />
                      </td>
                      <td className="px-3 py-3 text-xs uppercase">{u.language}</td>
                      <td className="px-3 py-3 text-xs">{u.timezone}</td>
                      <td className="numeric px-3 py-3 text-xs text-muted-foreground">
                        {formatDateTime(u.created_at)}
                      </td>
                      <td className="numeric px-3 py-3 text-xs text-muted-foreground">
                        {u.last_login_at ? formatRelative(u.last_login_at) : t("admin.users.never")}
                      </td>
                      <td className="space-y-2 px-3 py-3">
                        <RowActions user={u} self={u.id === auth.user?.id} onNotice={setNotice} />
                        <SecurityActions user={u} self={u.id === auth.user?.id} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul
              className="divide-y divide-border md:grid md:grid-cols-2 md:gap-px md:divide-y-0 md:bg-border xl:hidden"
              data-testid="users-cards"
            >
              {users.map((u) => (
                <li
                  key={u.id}
                  className="space-y-2.5 bg-card p-4"
                  data-testid={`user-card-${u.id}`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="break-words font-medium">
                        {u.display_name}
                        {u.id === auth.user?.id ? (
                          <span className="ml-1.5 text-caption text-gold">
                            ({t("admin.users.you")})
                          </span>
                        ) : null}
                      </div>
                      <div className="break-all text-caption text-muted-foreground">{u.email}</div>
                    </div>
                    <RoleBadge role={u.role} />
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                    <StatusDot status={u.status} />
                    <span className="uppercase">{u.language}</span>
                    <span>{u.timezone}</span>
                    <span>
                      {t("admin.users.lastLogin")}:{" "}
                      {u.last_login_at ? formatRelative(u.last_login_at) : t("admin.users.never")}
                    </span>
                  </div>
                  <SecurityBadges user={u} />
                  <MembershipCell user={u} />
                  <RowActions user={u} self={u.id === auth.user?.id} onNotice={setNotice} />
                  <SecurityActions user={u} self={u.id === auth.user?.id} />
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
      <PrivacyRequestsCard />
    </div>
  );
}
