/**
 * /activate (plan UX, A7, section 19, steps 2 and 3): the invitation's link. The reader creates their password - the
 * rule with its meter -, keeps or changes the language and the time zone the owner chose, and is signed in; the
 * consents come right after, the gate's own boxes (A4), recorded as given at the activation. A link that no longer
 * works says so in one way, whatever the reason, and offers a new one (the same answer whatever happens).
 */
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Loader2, MapPin, UserCheck } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { forgetLinkFromAddress, readLinkToken } from "@/lib/auth/linkToken";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import type { Language } from "@/lib/api/v1/types_auth";
import { isLocale, t } from "@/lib/i18n";
import { detectTimeZone, listTimeZones, zoneName } from "@/lib/time";
import { ConsentGate } from "@/product/legal/ConsentGate";
import { errorMessage } from "@/product/shared/States";
import { AccountShell, Notice, SideLink, accountButton, accountInput } from "./AccountShell";
import { passwordReady } from "@/lib/auth/passwordRule";
import { NewPassword } from "./NewPassword";
import { stepError } from "./stepError";

type LinkState = "checking" | "ready" | "invalid" | "off" | "failed";

function stateOf(error: unknown, pending: boolean, token: string | null): LinkState {
  if (!token) return "invalid";
  if (pending) return "checking";
  if (error instanceof LiveApiError) {
    if (error.status === 404) return "off";
    if (error.status === 410) return "invalid";
  }
  return error ? "failed" : "ready";
}

export function ActivatePage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [token] = useState(() => readLinkToken());
  useEffect(() => forgetLinkFromAddress(), []);
  const [activated, setActivated] = useState(false);
  // Under "auth": signing in drops every other cached query (a new session), and this one must not be asked again -
  // the link has just been used. Once activated, it is never asked again.
  const info = useQuery({
    queryKey: ["auth", "invitation", token],
    queryFn: () => v1.checkInvitation(token ?? ""),
    enabled: !!token && !activated,
    retry: false,
    staleTime: Infinity,
  });
  const state = stateOf(info.error, info.isPending && !!token, token);
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [language, setLanguage] = useState<Language>("es");
  const [zone, setZone] = useState("America/Bogota");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [renewed, setRenewed] = useState<"idle" | "busy" | "sent" | "failed">("idle");
  const filled = useRef(false);
  const zones = useMemo(listTimeZones, []);
  const device = detectTimeZone();

  // The owner's choices fill the form once; the page speaks the invitation's language from the start.
  useEffect(() => {
    if (!info.data || filled.current) return;
    filled.current = true;
    setLanguage(info.data.language);
    setZone(info.data.timezone);
    if (isLocale(info.data.language) && info.data.language !== auth.locale)
      void auth.setLocale(info.data.language);
  }, [info.data, auth]);

  // Activated and nothing owed (or the consents just accepted): into the product.
  const due = auth.user?.consents_due ?? [];
  useEffect(() => {
    if (activated && auth.status === "signed-in" && due.length === 0) {
      void navigate({ to: "/home", replace: true });
    }
  }, [activated, auth.status, due.length, navigate]);

  if (activated && auth.status === "signed-in" && due.length > 0) {
    return <ConsentGate due={due} source="activation" />;
  }

  const email = info.data?.email ?? "";
  const name = info.data?.display_name;
  const ready = passwordReady(password, repeat, { email, name });

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!token || !ready || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const who = await v1.activate({ token, password, language, timezone: zone });
      setActivated(true);
      auth.completeStep(who);
    } catch (err) {
      setFailure(stepError(err));
    } finally {
      setBusy(false);
    }
  }

  async function renew() {
    if (!token) return;
    setRenewed("busy");
    try {
      await v1.renewInvitation(token);
      setRenewed("sent");
    } catch {
      setRenewed("failed");
    }
  }

  if (state === "checking" || activated) {
    return (
      <AccountShell title={t("auth.account.activateTitle")} testId="activate-page">
        <Loader2 aria-hidden className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
      </AccountShell>
    );
  }
  if (state === "off") {
    return (
      <AccountShell title={t("auth.account.activateTitle")} testId="activate-page">
        <Notice tone="info" testId="self-service-off">
          {t("auth.account.off")}
        </Notice>
        <SideLink href="/login">{t("auth.account.toLogin")}</SideLink>
      </AccountShell>
    );
  }
  if (state === "invalid" || state === "failed") {
    return (
      <AccountShell title={t("auth.account.activateTitle")} testId="activate-page">
        {state === "failed" ? (
          <Notice tone="error">{errorMessage(info.error)}</Notice>
        ) : (
          <Notice tone="warning" testId="link-invalid">
            {t("auth.account.inviteInvalid")}
          </Notice>
        )}
        {token && state === "invalid" ? (
          renewed === "sent" ? (
            <Notice tone="ok" testId="renew-sent">
              {t("auth.account.inviteRenewed")}
            </Notice>
          ) : (
            <button
              type="button"
              onClick={() => void renew()}
              disabled={renewed === "busy"}
              className={accountButton}
              data-testid="renew-invitation"
            >
              {renewed === "busy" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("auth.account.inviteRenew")}
            </button>
          )
        ) : null}
        {renewed === "failed" ? <Notice tone="error">{t("errors.generic")}</Notice> : null}
        <SideLink href="/login">{t("auth.account.alreadyActive")}</SideLink>
      </AccountShell>
    );
  }

  return (
    <AccountShell
      title={t("auth.account.activateTitle")}
      subtitle={t("auth.account.activateSubtitle", { name: name ?? "" })}
      testId="activate-page"
    >
      <form
        onSubmit={(e) => void submit(e)}
        className="space-y-4"
        noValidate
        data-testid="activate-form"
      >
        <NewPassword
          email={email}
          name={name}
          value={password}
          onChange={setPassword}
          repeat={repeat}
          onRepeat={setRepeat}
        />
        <label className="block">
          <span className="text-xs font-medium text-muted-foreground">
            {t("auth.account.language")}
          </span>
          <select
            value={language}
            onChange={(e) => setLanguage(e.target.value as Language)}
            className={accountInput}
            data-testid="activate-language"
          >
            <option value="es">Español</option>
            <option value="en">English</option>
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-medium text-muted-foreground">
            {t("auth.account.timezone")}
          </span>
          <select
            value={zone}
            onChange={(e) => setZone(e.target.value)}
            className={accountInput}
            data-testid="activate-timezone"
          >
            {zones.map((z) => (
              <option key={z} value={z}>
                {z.replace(/_/g, " ")}
              </option>
            ))}
          </select>
          <span className="mt-1 block text-xs text-muted-foreground">{zoneName(zone)}</span>
        </label>
        {device !== zone ? (
          <button
            type="button"
            onClick={() => setZone(device)}
            className="tap-y relative inline-flex items-center gap-1.5 text-xs font-medium text-primary"
          >
            <MapPin aria-hidden className="h-3.5 w-3.5" />
            {t("auth.account.useDeviceZone", { zone: device.replace(/_/g, " ") })}
          </button>
        ) : null}
        {failure ? (
          <Notice tone="error" testId="activate-error">
            {failure}
          </Notice>
        ) : null}
        <button
          type="submit"
          disabled={!ready || busy}
          className={accountButton}
          data-testid="activate-submit"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserCheck className="h-4 w-4" />}
          {busy ? t("auth.account.activating") : t("auth.account.activate")}
        </button>
      </form>
    </AccountShell>
  );
}
