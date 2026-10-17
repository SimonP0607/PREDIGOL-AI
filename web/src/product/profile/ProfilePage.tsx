/** Account, language, time zone and password. Preferences are stored on the account. */
import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "@tanstack/react-router";
import {
  Check,
  Globe2,
  History,
  KeyRound,
  Languages,
  Loader2,
  LogOut,
  MapPin,
  MonitorSmartphone,
  ShieldCheck,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import { LOCALES, t, useI18n } from "@/lib/i18n";
import { detectTimeZone, formatDateTime, formatTime, listTimeZones, zoneAbbrev } from "@/lib/time";
import { Card, PageTitle, errorMessage } from "@/product/shared/States";
import { LiveApiError } from "@/lib/api/v1/client";
import { cn } from "@/lib/utils";
import { AccessPanel, SessionsPanel, TwoFactorPanel } from "./SecurityPanels";

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 border-b border-border/70 py-3 last:border-0 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="min-w-0 text-sm">{children}</span>
    </div>
  );
}

function TimeZonePicker() {
  const auth = useAuth();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const zones = useMemo(listTimeZones, []);
  const device = detectTimeZone();
  const current = auth.timeZone;
  const matches = useMemo(() => {
    const q = query.trim().toLowerCase().replace(/\s+/g, "_");
    const list = q ? zones.filter((z) => z.toLowerCase().includes(q)) : zones;
    return list.slice(0, 60);
  }, [query, zones]);

  async function choose(zone: string) {
    setBusy(zone);
    setError(null);
    try {
      await auth.updatePreferences({ timezone: zone });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className="numeric rounded-md border border-gold/40 bg-gold-soft px-2 py-1 text-sm font-semibold text-gold-strong"
          data-testid="current-timezone"
        >
          {current} · {zoneAbbrev(Date.now(), current)}
        </span>
        <span className="text-xs text-muted-foreground">
          {t("profile.currentTime", { time: formatTime(Date.now()) })}
        </span>
      </div>
      {device !== current ? (
        <button
          type="button"
          onClick={() => void choose(device)}
          className="inline-flex items-center gap-1.5 rounded-md border border-border-strong px-2.5 py-1.5 text-xs font-medium hover:bg-elevated"
        >
          <MapPin aria-hidden className="h-3.5 w-3.5" />
          {t("profile.detect", { zone: device })}
        </button>
      ) : null}
      <input
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t("profile.searchZone")}
        aria-label={t("profile.searchZone")}
        data-testid="timezone-search"
        className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none pointer-coarse:h-11"
      />
      <ul
        className="max-h-64 overflow-y-auto rounded-md border border-border"
        role="listbox"
        aria-label={t("profile.timezone")}
      >
        {matches.map((z) => (
          <li key={z}>
            <button
              type="button"
              role="option"
              aria-selected={z === current}
              data-testid={`tz-${z}`}
              onClick={() => void choose(z)}
              disabled={busy !== null}
              className={cn(
                "flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-sm hover:bg-elevated pointer-coarse:min-h-11",
                z === current && "bg-elevated",
              )}
            >
              <span className="min-w-0 break-words">{z.replace(/_/g, " ")}</span>
              <span className="flex shrink-0 items-center gap-2 text-caption text-muted-foreground">
                {zoneAbbrev(Date.now(), z)}
                {busy === z ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : z === current ? (
                  <Check className="h-3.5 w-3.5 text-primary" />
                ) : null}
              </span>
            </button>
          </li>
        ))}
      </ul>
      {error ? (
        <p role="alert" className="text-xs text-negative">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string; problems?: string[] } | null>(
    null,
  );

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      await v1.changePassword(current, next);
      setCurrent("");
      setNext("");
      setMessage({ ok: true, text: t("profile.passwordChanged") });
    } catch (err) {
      const problems =
        err instanceof LiveApiError ? err.problems.map((p) => t(`errors.problem.${p}`)) : [];
      setMessage({ ok: false, text: errorMessage(err), problems });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="grid gap-3 sm:grid-cols-2">
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("profile.currentPassword")}</span>
        <input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
          className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none pointer-coarse:h-11"
        />
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">{t("profile.newPassword")}</span>
        <input
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(e) => setNext(e.target.value)}
          className="mt-1 h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus:border-primary focus:outline-none pointer-coarse:h-11"
        />
      </label>
      <p className="text-caption text-subtle-foreground sm:col-span-2">
        {t("profile.passwordRules")}
      </p>
      {message ? (
        <div
          role={message.ok ? "status" : "alert"}
          className={cn("text-xs sm:col-span-2", message.ok ? "text-positive" : "text-negative")}
        >
          {message.text}
          {message.problems?.length ? (
            <ul className="mt-1 list-disc pl-4">
              {message.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
      <div className="sm:col-span-2">
        <button
          type="submit"
          disabled={busy || !current || !next}
          className="tap-y relative inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          {t("profile.changePassword")}
        </button>
      </div>
    </form>
  );
}

export function ProfilePage() {
  const auth = useAuth();
  const { locale } = useI18n();
  const navigate = useNavigate();
  const user = auth.user;
  if (!user) return null;
  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <PageTitle title={t("profile.title")} subtitle={t("profile.subtitle")} />

      <Card className="p-5">
        <h2 className="mb-1 font-display text-base font-semibold">{t("profile.account")}</h2>
        <Row label={t("profile.displayName")}>{user.display_name}</Row>
        <Row label={t("profile.email")}>{user.email}</Row>
        <Row label={t("profile.role")}>
          <span className="rounded-full border border-gold/40 bg-gold-soft px-2 py-0.5 text-xs font-bold tracking-wider text-gold-strong">
            {user.role}
          </span>
        </Row>
        <Row label={t("profile.sessionLabel")}>
          <span className="numeric text-xs">{formatDateTime(user.session_expires_at)}</span>
        </Row>
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 flex items-center gap-2 font-display text-base font-semibold">
          <Languages aria-hidden className="h-4 w-4 text-primary" />
          {t("profile.language")}
        </h2>
        <p className="mb-3 text-xs text-muted-foreground">{t("profile.languageHelp")}</p>
        <div className="flex gap-2" role="radiogroup" aria-label={t("profile.language")}>
          {LOCALES.map((l) => (
            <button
              key={l}
              type="button"
              role="radio"
              aria-checked={locale === l}
              data-testid={`profile-lang-${l}`}
              onClick={() => void auth.setLocale(l)}
              className={cn(
                "rounded-md border px-4 py-2 text-sm font-semibold pointer-coarse:min-h-11",
                locale === l
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border-strong hover:bg-elevated",
              )}
            >
              {l === "es" ? "Español" : "English"}
            </button>
          ))}
        </div>
      </Card>

      <Card className="p-5">
        <h2 className="mb-1 flex items-center gap-2 font-display text-base font-semibold">
          <Globe2 aria-hidden className="h-4 w-4 text-primary" />
          {t("profile.timezone")}
        </h2>
        <p className="mb-3 text-xs text-muted-foreground">{t("profile.timezoneHelp")}</p>
        <TimeZonePicker />
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 flex items-center gap-2 font-display text-base font-semibold">
          <KeyRound aria-hidden className="h-4 w-4 text-primary" />
          {t("profile.security")}
        </h2>
        <PasswordForm />
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 flex items-center gap-2 font-display text-base font-semibold">
          <ShieldCheck aria-hidden className="h-4 w-4 text-primary" />
          {t("profile.securityPanel.mfaTitle")}
        </h2>
        <TwoFactorPanel user={user} />
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 flex items-center gap-2 font-display text-base font-semibold">
          <MonitorSmartphone aria-hidden className="h-4 w-4 text-primary" />
          {t("profile.securityPanel.sessionsTitle")}
        </h2>
        <SessionsPanel />
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 flex items-center gap-2 font-display text-base font-semibold">
          <History aria-hidden className="h-4 w-4 text-primary" />
          {t("profile.securityPanel.accessTitle")}
        </h2>
        <AccessPanel />
      </Card>

      <button
        type="button"
        onClick={() => void auth.signOut().then(() => navigate({ to: "/login" }))}
        className="inline-flex items-center gap-2 rounded-md border border-negative/40 px-4 py-2 text-sm font-medium text-negative hover:bg-negative-soft pointer-coarse:min-h-11"
      >
        <LogOut aria-hidden className="h-4 w-4" />
        {t("profile.signOut")}
      </button>
    </div>
  );
}
