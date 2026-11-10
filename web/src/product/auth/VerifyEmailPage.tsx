/**
 * /verify-email (UX-038): the link of the registration's e-mail, valid 24 hours and once. The address is proven by the
 * link; the password the person chose is typed again (the account has no other proof until now). Then the account is
 * active and signed in - and still has no access to PrediGol: that is decided later, by the membership. A link that
 * does not work says so in one way, whatever the reason, and asks for the address to send a new one.
 */
import { useEffect, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { Eye, EyeOff, Loader2, MailCheck } from "lucide-react";
import { useAuth } from "@/lib/auth/AuthProvider";
import { forgetLinkFromAddress, readLinkToken } from "@/lib/auth/linkToken";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { isLocale, t } from "@/lib/i18n";
import { errorMessage } from "@/product/shared/States";
import { AccountShell, Notice, SideLink, accountButton, accountInput } from "./AccountShell";
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

export function VerifyEmailPage() {
  const auth = useAuth();
  const navigate = useNavigate();
  const [token] = useState(() => readLinkToken());
  useEffect(() => forgetLinkFromAddress(), []);
  const [done, setDone] = useState(false);
  // Under "auth": signing in drops every other cached query, and a used link must not be asked about again.
  const info = useQuery({
    queryKey: ["auth", "verify", token],
    queryFn: () => v1.checkVerification(token ?? ""),
    enabled: !!token && !done,
    retry: false,
    staleTime: Infinity,
  });
  const state = stateOf(info.error, info.isPending && !!token, token);
  const [password, setPassword] = useState("");
  const [show, setShow] = useState(false);
  // Forgot the password chosen when registering: the link proves the mailbox, so a new one replaces it (UX-084).
  const [replace, setReplace] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [linkGone, setLinkGone] = useState(false);
  const [askEmail, setAskEmail] = useState("");
  const [asked, setAsked] = useState<"idle" | "busy" | "sent" | "failed">("idle");

  // The page speaks the language the person registered in.
  useEffect(() => {
    const language = info.data?.language;
    if (language && isLocale(language) && language !== auth.locale) void auth.setLocale(language);
  }, [info.data?.language, auth]);

  // Confirmed and signed in: into the product (its gates decide what is open).
  useEffect(() => {
    if (done && auth.status === "signed-in") void navigate({ to: "/home", replace: true });
  }, [done, auth.status, navigate]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!token || !password || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const who = await v1.verifyEmail(
        replace ? { token, password, replace_password: true } : { token, password },
      );
      setDone(true);
      auth.completeStep(who);
    } catch (err) {
      if (err instanceof LiveApiError && err.status === 410) setLinkGone(true);
      else setFailure(stepError(err));
      setPassword("");
    } finally {
      setBusy(false);
    }
  }

  async function ask(e: FormEvent) {
    e.preventDefault();
    if (!askEmail.trim() || asked === "busy") return;
    setAsked("busy");
    try {
      await v1.resendVerification(askEmail.trim());
      setAsked("sent");
    } catch {
      setAsked("failed");
    }
  }

  if (state === "checking" || done) {
    return (
      <AccountShell title={t("auth.verify.title")} testId="verify-page">
        <Loader2 aria-hidden className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
      </AccountShell>
    );
  }
  if (state === "off") {
    return (
      <AccountShell title={t("auth.verify.title")} testId="verify-page">
        <Notice tone="info" testId="signup-closed">
          {t("auth.signup.closed")}
        </Notice>
        <SideLink href="/login">{t("auth.account.toLogin")}</SideLink>
      </AccountShell>
    );
  }
  if (state === "invalid" || state === "failed" || linkGone) {
    return (
      <AccountShell title={t("auth.verify.title")} testId="verify-page">
        {state === "failed" ? (
          <Notice tone="error">{errorMessage(info.error)}</Notice>
        ) : (
          <Notice tone="warning" testId="link-invalid">
            {t("auth.verify.invalid")}
          </Notice>
        )}
        {asked === "sent" ? (
          <Notice tone="ok" testId="verify-asked">
            {t("auth.resendConfirmationSent")}
          </Notice>
        ) : (
          <form onSubmit={(e) => void ask(e)} className="space-y-3" noValidate>
            <p className="text-sm text-muted-foreground">{t("auth.verify.askAgain")}</p>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">{t("auth.email")}</span>
              <input
                type="email"
                name="email"
                autoComplete="username"
                inputMode="email"
                value={askEmail}
                onChange={(e) => setAskEmail(e.target.value)}
                className={accountInput}
                data-testid="verify-ask-email"
              />
            </label>
            <button
              type="submit"
              disabled={!askEmail.trim() || asked === "busy"}
              className={accountButton}
              data-testid="verify-ask-submit"
            >
              {asked === "busy" ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
              {t("auth.verify.askSubmit")}
            </button>
          </form>
        )}
        {asked === "failed" ? <Notice tone="error">{t("errors.generic")}</Notice> : null}
        <SideLink href="/login">{t("auth.account.toLogin")}</SideLink>
      </AccountShell>
    );
  }

  return (
    <AccountShell
      title={t("auth.verify.title")}
      subtitle={t("auth.verify.subtitle", { name: info.data?.display_name ?? "" })}
      testId="verify-page"
    >
      <form
        onSubmit={(e) => void submit(e)}
        className="space-y-4"
        noValidate
        data-testid="verify-form"
      >
        {/* The address as the username: the password manager recognises the account the password belongs to. */}
        <input
          type="email"
          name="username"
          autoComplete="username"
          value={info.data?.email ?? ""}
          readOnly
          hidden
          aria-hidden
          tabIndex={-1}
        />
        <label className="block">
          <span className="text-xs font-medium text-muted-foreground">
            {replace ? t("auth.verify.newPassword") : t("auth.verify.password")}
          </span>
          <span className="relative mt-1 block">
            <input
              type={show ? "text" : "password"}
              name="password"
              autoComplete={replace ? "new-password" : "current-password"}
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={`${accountInput} mt-0 pr-12`}
              data-testid="verify-password"
            />
            <button
              type="button"
              onClick={() => setShow((v) => !v)}
              aria-label={show ? t("auth.hidePassword") : t("auth.showPassword")}
              className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-muted-foreground hover:text-foreground"
            >
              {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
            </button>
          </span>
        </label>
        {replace ? (
          <p className="text-xs text-muted-foreground" data-testid="verify-replace-help">
            {t("auth.verify.newPasswordHelp")}
          </p>
        ) : null}
        {failure ? (
          <Notice tone="error" testId="verify-error">
            {failure}
          </Notice>
        ) : null}
        <button
          type="submit"
          disabled={!password || busy}
          className={accountButton}
          data-testid="verify-submit"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <MailCheck className="h-4 w-4" />}
          {busy ? t("auth.verify.submitting") : t("auth.verify.submit")}
        </button>
        <button
          type="button"
          onClick={() => {
            setReplace((v) => !v);
            setPassword("");
            setFailure(null);
          }}
          className="tap-y relative block w-full text-center text-xs font-medium text-primary underline-offset-2 hover:underline"
          data-testid="verify-toggle-replace"
        >
          {replace ? t("auth.verify.useChosen") : t("auth.verify.forgot")}
        </button>
      </form>
    </AccountShell>
  );
}
