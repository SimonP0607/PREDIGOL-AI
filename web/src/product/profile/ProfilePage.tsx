/**
 * The account centre (plan UX, B1; section 21): the profile in eight blocks - Cuenta, Fútbol, Idioma y zona,
 * Notificaciones, Privacidad, Seguridad, Membresía and Ayuda - each a card that folds (folded under 1024 px, with the one
 * line it says from GET /me/account; open at a desk). An e-mail's button or a page leads to a block by its address:
 * /profile#privacy, #notifications, #membership, #football. Preferences are stored on the account.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type FormEvent,
  type SetStateAction,
} from "react";
import { useNavigate } from "@tanstack/react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  CalendarClock,
  Check,
  KeyRound,
  Languages,
  LifeBuoy,
  Lock,
  Loader2,
  LogOut,
  MapPin,
  ShieldCheck,
  Star,
  UserRound,
} from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { Me } from "@/lib/api/v1/types_auth";
import { LOCALES, t, useI18n } from "@/lib/i18n";
import { LOCALE_NAMES } from "@/lib/i18n/catalogs";
import { detectTimeZone, formatTime, listTimeZones, zoneAbbrev, zoneName } from "@/lib/time";
import { PageTitle, errorMessage } from "@/product/shared/States";
import { LiveApiError } from "@/lib/api/v1/client";
import { cn } from "@/lib/utils";
import { AccessPanel, SessionsPanel, TwoFactorPanel } from "./SecurityPanels";
import { NotificationsPanel } from "./NotificationsPanel";
import { MembershipCard } from "@/product/membership/MembershipCard";
import { PrivacyPanel } from "./PrivacyPanel";
import { FootballPanel } from "@/product/favorites/FootballPanel";
import { AccountPanel } from "./AccountPanel";
import { useGuideScreen } from "@/product/guides/context";
import { Block } from "./Block";
import { HelpPanel } from "./HelpPanel";
import { BLOCKS, blockOfHash, blockSummary, startsOpen, type BlockKey } from "./centre";

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
        {/* The zone in words, in the reader's language (plan UX, A1, F09). */}
        <span className="text-xs text-foreground" data-testid="current-timezone-name">
          {zoneName(current)}
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
          // The item is only a wrapper: the option is the button, so the listbox owns its options (axe, line base of
          // A0: aria-required-parent, listitem and aria-required-children on this list).
          <li key={z} role="presentation">
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

function Subsection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3 border-t border-border/70 pt-4 first:border-0 first:pt-0">
      <h3 className="font-display text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function RegionPanel() {
  const auth = useAuth();
  const { locale } = useI18n();
  return (
    <div className="space-y-4" data-testid="region-panel">
      <Subsection title={t("profile.language")}>
        <p className="text-xs text-muted-foreground">{t("profile.languageHelp")}</p>
        <div className="flex gap-2" role="radiogroup" aria-label={t("profile.language")}>
          {LOCALES.map((l) => (
            <button
              key={l}
              type="button"
              role="radio"
              aria-checked={locale === l}
              lang={l}
              data-testid={`profile-lang-${l}`}
              onClick={() => void auth.setLocale(l)}
              className={cn(
                "rounded-md border px-4 py-2 text-sm font-semibold pointer-coarse:min-h-11",
                locale === l
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border-strong hover:bg-elevated",
              )}
            >
              {LOCALE_NAMES[l]}
            </button>
          ))}
        </div>
      </Subsection>
      <Subsection title={t("profile.timezone")}>
        <p className="text-xs text-muted-foreground">{t("profile.timezoneHelp")}</p>
        <TimeZonePicker />
      </Subsection>
    </div>
  );
}

function SecurityPanel({ user }: { user: Me }) {
  return (
    <div className="space-y-4" data-testid="security-panel">
      <Subsection title={t("profile.centre.password")}>
        <PasswordForm />
      </Subsection>
      <Subsection title={t("profile.securityPanel.mfaTitle")}>
        <TwoFactorPanel user={user} />
      </Subsection>
      <Subsection title={t("profile.securityPanel.sessionsTitle")}>
        <SessionsPanel />
      </Subsection>
      <Subsection title={t("profile.securityPanel.accessTitle")}>
        <AccessPanel />
      </Subsection>
    </div>
  );
}

type OpenState = Record<BlockKey, boolean>;

/** Which blocks start open: all of them at a desk, none under 1024 px - and always the one the address names. */
function initialOpen(): OpenState {
  const open = startsOpen();
  const named = typeof window === "undefined" ? null : blockOfHash(window.location.hash);
  return Object.fromEntries(BLOCKS.map((key) => [key, open || key === named])) as OpenState;
}

/** The block an address names (#privacy) opens and comes into view, on arrival and when the address changes. */
function useNamedBlock(ready: boolean, setOpen: Dispatch<SetStateAction<OpenState>>): void {
  useEffect(() => {
    if (!ready || typeof window === "undefined") return;
    const go = () => {
      const key = blockOfHash(window.location.hash);
      if (!key) return;
      setOpen((prev) => (prev[key] ? prev : { ...prev, [key]: true }));
      window.requestAnimationFrame(() =>
        document.getElementById(key)?.scrollIntoView({ block: "start" }),
      );
    };
    go();
    window.addEventListener("hashchange", go);
    return () => window.removeEventListener("hashchange", go);
  }, [ready, setOpen]);
}

export function ProfilePage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const user = auth.user;
  const summary = useQuery({ ...live.account, enabled: Boolean(user) });
  const [open, setOpen] = useState<OpenState>(initialOpen);
  useNamedBlock(Boolean(user), setOpen);
  useGuideScreen("profile", { ready: Boolean(user) });
  const toggle = useCallback(
    (key: BlockKey) => {
      setOpen((prev) => ({ ...prev, [key]: !prev[key] }));
      // folding a block after a change in it: its line says the new state
      if (open[key]) void qc.invalidateQueries({ queryKey: ["me", "account"] });
    },
    [open, qc],
  );
  const data = summary.data;
  const line = useMemo(() => (key: BlockKey) => (data ? blockSummary(key, data) : null), [data]);
  if (!user) return null;
  const block = (key: BlockKey) => ({
    id: key,
    summary: line(key),
    open: open[key],
    onToggle: () => toggle(key),
  });
  return (
    <div className="mx-auto max-w-3xl space-y-3" data-testid="account-centre">
      <PageTitle
        guide="profile"
        title={t("profile.title")}
        subtitle={t("profile.centre.subtitle")}
      />
      {summary.isError ? (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 rounded-md border border-border px-4 py-3 text-xs text-muted-foreground"
          data-testid="account-summary-error"
        >
          {t("profile.centre.summaryError")}
          <button
            type="button"
            onClick={() => void summary.refetch()}
            className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-3 text-xs font-medium hover:bg-elevated"
          >
            {t("common.retry")}
          </button>
        </div>
      ) : null}

      <Block
        {...block("account")}
        icon={<UserRound className="h-5 w-5" />}
        title={t("profile.account")}
      >
        <AccountPanel user={user} summary={data} />
      </Block>
      <Block
        {...block("football")}
        icon={<Star className="h-5 w-5" />}
        title={t("onboarding.panel.title")}
      >
        <FootballPanel />
      </Block>
      <Block
        {...block("region")}
        icon={<Languages className="h-5 w-5" />}
        title={t("profile.centre.region")}
      >
        <RegionPanel />
      </Block>
      <Block
        {...block("notifications")}
        icon={<Bell className="h-5 w-5" />}
        title={t("profile.notifications.title")}
      >
        <NotificationsPanel />
      </Block>
      <Block
        {...block("privacy")}
        icon={<Lock className="h-5 w-5" />}
        title={t("legal.privacy.title")}
      >
        <PrivacyPanel />
      </Block>
      <Block
        {...block("security")}
        icon={<ShieldCheck className="h-5 w-5" />}
        title={t("profile.security")}
      >
        <SecurityPanel user={user} />
      </Block>
      {user.membership ? (
        <Block
          {...block("membership")}
          icon={<CalendarClock className="h-5 w-5" />}
          title={t("profile.membership.title")}
        >
          <MembershipCard />
        </Block>
      ) : null}
      <Block
        {...block("help")}
        icon={<LifeBuoy className="h-5 w-5" />}
        title={t("profile.centre.help.title")}
      >
        <HelpPanel summary={data} />
      </Block>

      <button
        type="button"
        onClick={() => void auth.signOut().then(() => navigate({ to: "/login" }))}
        className="mt-2 inline-flex items-center gap-2 rounded-md border border-negative/40 px-4 py-2 text-sm font-medium text-negative hover:bg-negative-soft pointer-coarse:min-h-11"
      >
        <LogOut aria-hidden className="h-4 w-4" />
        {t("profile.signOut")}
      </button>
    </div>
  );
}
