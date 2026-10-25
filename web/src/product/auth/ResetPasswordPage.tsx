/**
 * /reset-password (plan UX, A7; R25 of the security plan): the e-mail's link, valid 30 minutes and once. The new
 * password - the rule with its meter - and, when the account has a second factor, a code from its app or a recovery
 * code first: the link alone never changes the password of such an account. Afterwards every session of the account
 * has ended and the reader signs in again; the second factor stays as it was.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { KeyRound, Loader2 } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { forgetLinkFromAddress, readLinkToken } from "@/lib/auth/linkToken";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/product/shared/States";
import { AccountShell, Notice, SideLink, accountButton, accountInput } from "./AccountShell";
import { passwordReady } from "@/lib/auth/passwordRule";
import { NewPassword } from "./NewPassword";
import { stepError } from "./stepError";

export function ResetPasswordPage() {
  const auth = useAuth();
  const [token] = useState(() => readLinkToken());
  useEffect(() => forgetLinkFromAddress(), []);
  const [done, setDone] = useState(false);
  // Under "auth", and never asked again once the password changed: signing out (this browser's session ends with the
  // others) clears the cache, and the used link must not be asked about again.
  const info = useQuery({
    queryKey: ["auth", "reset", token],
    queryFn: () => v1.checkReset(token ?? ""),
    enabled: !!token && !done,
    retry: false,
    staleTime: Infinity,
  });
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [code, setCode] = useState("");
  const [useRecovery, setUseRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [linkGone, setLinkGone] = useState(false);

  const off = info.error instanceof LiveApiError && info.error.status === 404;
  const invalid =
    !token || linkGone || (info.error instanceof LiveApiError && info.error.status === 410);
  const email = info.data?.email ?? "";
  const mfa = info.data?.mfa ?? false;
  const codeReady =
    !mfa ||
    (useRecovery
      ? code.replace(/[^a-z0-9]/gi, "").length >= 10
      : code.replace(/\D/g, "").length === 6);
  const ready = passwordReady(password, repeat, { email, hasMfa: mfa }) && codeReady;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!token || !ready || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await v1.resetPassword({
        token,
        password,
        ...(mfa ? (useRecovery ? { recovery_code: code } : { code }) : {}),
      });
      setDone(true);
      // Every session of the account ended: this browser's too, when it was signed in as it.
      if (auth.user?.email === email) await auth.signOut();
    } catch (err) {
      if (err instanceof LiveApiError && err.status === 410) setLinkGone(true);
      else setFailure(stepError(err));
    } finally {
      setBusy(false);
    }
  }

  const title = t("auth.account.resetTitle");
  if (done) {
    return (
      <AccountShell title={title} testId="reset-page">
        <Notice tone="ok" testId="reset-done">
          {t("auth.account.resetDone")}
        </Notice>
        <a href="/login" className={accountButton} data-testid="reset-to-login">
          {t("auth.account.toLoginNow")}
        </a>
      </AccountShell>
    );
  }
  if (token && !invalid && info.isPending) {
    return (
      <AccountShell title={title} testId="reset-page">
        <Loader2 aria-hidden className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
      </AccountShell>
    );
  }
  if (off) {
    return (
      <AccountShell title={title} testId="reset-page">
        <Notice tone="info" testId="self-service-off">
          {t("auth.account.forgotOff")}
        </Notice>
        <SideLink href="/login">{t("auth.account.toLogin")}</SideLink>
      </AccountShell>
    );
  }
  if (invalid || info.isError) {
    return (
      <AccountShell title={title} testId="reset-page">
        {invalid ? (
          <Notice tone="warning" testId="link-invalid">
            {t("auth.account.resetInvalid")}
          </Notice>
        ) : (
          <Notice tone="error">{errorMessage(info.error)}</Notice>
        )}
        <a href="/forgot-password" className={accountButton} data-testid="reset-ask-again">
          {t("auth.account.askAgain")}
        </a>
        <SideLink href="/login">{t("auth.account.toLogin")}</SideLink>
      </AccountShell>
    );
  }

  return (
    <AccountShell title={title} subtitle={t("auth.account.resetSubtitle")} testId="reset-page">
      <form
        onSubmit={(e) => void submit(e)}
        className="space-y-4"
        noValidate
        data-testid="reset-form"
      >
        <NewPassword
          email={email}
          hasMfa={mfa}
          value={password}
          onChange={setPassword}
          repeat={repeat}
          onRepeat={setRepeat}
        />
        {mfa ? (
          <div
            className="space-y-2 rounded-md border border-border p-3"
            data-testid="reset-second-factor"
          >
            <p className="text-xs text-muted-foreground">{t("auth.account.resetMfa")}</p>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                {useRecovery ? t("auth.steps.recoveryCode") : t("auth.steps.code")}
              </span>
              <input
                inputMode={useRecovery ? "text" : "numeric"}
                autoComplete="one-time-code"
                maxLength={useRecovery ? 24 : 7}
                value={code}
                onChange={(e) =>
                  setCode(useRecovery ? e.target.value : e.target.value.replace(/[^0-9 ]/g, ""))
                }
                className={cn(accountInput, "numeric tracking-widest")}
                data-testid="reset-code"
              />
            </label>
            <button
              type="button"
              onClick={() => {
                setUseRecovery((v) => !v);
                setCode("");
              }}
              className="tap-y relative text-xs font-medium text-primary"
            >
              {useRecovery ? t("auth.steps.useApp") : t("auth.steps.useRecovery")}
            </button>
          </div>
        ) : null}
        {failure ? (
          <Notice tone="error" testId="reset-error">
            {failure}
          </Notice>
        ) : null}
        <button
          type="submit"
          disabled={!ready || busy}
          className={accountButton}
          data-testid="reset-submit"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <KeyRound className="h-4 w-4" />}
          {t("auth.account.resetSubmit")}
        </button>
      </form>
    </AccountShell>
  );
}
