/** Accounts: who can sign in, with which role. SUPER_ADMIN only (enforced by the API). */
import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Copy,
  KeyRound,
  Loader2,
  Lock,
  LogOut,
  Plus,
  RefreshCw,
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
import type { AdminUser, AdminUserCreate, Language, RoleKey } from "@/lib/api/v1/types_auth";
import { t } from "@/lib/i18n";
import { detectTimeZone, formatDateTime, formatRelative, listTimeZones } from "@/lib/time";
import { Card, ErrorState, SkeletonCards, errorMessage } from "@/product/shared/States";
import { cn } from "@/lib/utils";

const ROLES: RoleKey[] = ["USER", "SUPER_ADMIN"];

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
        className={cn("h-2 w-2 rounded-full", status === "active" ? "bg-positive" : "bg-negative")}
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

function CreateForm({ onDone }: { onDone: () => void }) {
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
  const field =
    "mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none";
  return (
    <form
      onSubmit={submit}
      className="grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-3"
      data-testid="create-user-form"
    >
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

function RowActions({ user, self }: { user: AdminUser; self: boolean }) {
  const qc = useQueryClient();
  const [confirm, setConfirm] = useState<"status" | "role" | null>(null);
  const [error, setError] = useState<string | null>(null);
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
  const btn = "rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-50";
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap gap-1.5">
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
  const btn = "rounded-md border px-2 py-1 text-xs font-medium disabled:opacity-50";
  const labels: Record<SecurityAction, string> = {
    password: t("admin.users.resetPassword"),
    mfa: t("admin.users.resetMfa"),
    sessions: t("admin.users.endSessions"),
    unlock: t("admin.users.unlock"),
    requireMfa: user.mfa_required
      ? t("admin.users.dropMfaRequirement")
      : t("admin.users.requireMfa"),
  };
  const available: SecurityAction[] = [
    "password",
    ...(user.mfa_enabled ? (["mfa"] as const) : []),
    ...(user.active_sessions > 0 && !self ? (["sessions"] as const) : []),
    ...(user.locked_until ? (["unlock"] as const) : []),
    ...(user.role !== "SUPER_ADMIN" ? (["requireMfa"] as const) : []),
  ];
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap gap-1.5">
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
  const [creating, setCreating] = useState(false);
  const users = q.data?.data ?? [];
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
              className="rounded-md border border-border-strong p-2 hover:bg-elevated"
            >
              <RefreshCw aria-hidden className={cn("h-4 w-4", q.isFetching && "animate-spin")} />
            </button>
            <button
              type="button"
              data-testid="new-user"
              onClick={() => setCreating((v) => !v)}
              className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground"
            >
              <Plus aria-hidden className="h-4 w-4" />
              {t("admin.users.newUser")}
            </button>
          </>
        }
      />
      {creating ? (
        <Card>
          <CreateForm onDone={() => setCreating(false)} />
        </Card>
      ) : null}
      <Card className="overflow-hidden">
        {q.isPending ? (
          <SkeletonCards className="p-4" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : (
          <>
            <div className="border-b border-border px-4 py-2 text-caption text-muted-foreground">
              {t("admin.users.count", { count: users.length })}
            </div>
            <div className="hidden overflow-x-auto md:block">
              <table className="w-full text-sm" data-testid="users-table">
                <thead className="text-left text-caption uppercase tracking-wider text-subtle-foreground">
                  <tr className="border-b border-border">
                    <th className="px-4 py-2 font-medium">{t("admin.users.user")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.role")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.status")}</th>
                    <th className="px-3 py-2 font-medium">{t("admin.users.security")}</th>
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
                      <td className="px-3 py-3 text-xs uppercase">{u.language}</td>
                      <td className="px-3 py-3 text-xs">{u.timezone}</td>
                      <td className="numeric px-3 py-3 text-xs text-muted-foreground">
                        {formatDateTime(u.created_at)}
                      </td>
                      <td className="numeric px-3 py-3 text-xs text-muted-foreground">
                        {u.last_login_at ? formatRelative(u.last_login_at) : t("admin.users.never")}
                      </td>
                      <td className="space-y-2 px-3 py-3">
                        <RowActions user={u} self={u.id === auth.user?.id} />
                        <SecurityActions user={u} self={u.id === auth.user?.id} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <ul className="divide-y divide-border md:hidden">
              {users.map((u) => (
                <li key={u.id} className="space-y-2 p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate font-medium">{u.display_name}</div>
                      <div className="truncate text-caption text-muted-foreground">{u.email}</div>
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
                  <RowActions user={u} self={u.id === auth.user?.id} />
                  <SecurityActions user={u} self={u.id === auth.user?.id} />
                </li>
              ))}
            </ul>
          </>
        )}
      </Card>
    </div>
  );
}
