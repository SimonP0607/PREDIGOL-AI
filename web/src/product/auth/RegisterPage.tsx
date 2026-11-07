/**
 * /register (UX-038, tramo 1 of the user's flow): a person opens their own account. Name, e-mail, mobile, a unique
 * nickname, a password and the four required consents - each box with the exact sentence the server stores and the
 * version it was shown - and one answer whatever the address: «revisa tu correo». The account is pending until the
 * e-mail's link is opened; creating it gives no access to anything. The page exists only while the API says the
 * registration is open (FBI_SIGNUP and its locks): otherwise it says so.
 */
import { useMemo, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Mail, UserPlus } from "lucide-react";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import type { Language } from "@/lib/api/v1/types_auth";
import type { ConsentKind } from "@/lib/api/v1/types_customer";
import { passwordReady } from "@/lib/auth/passwordRule";
import { t, useI18n } from "@/lib/i18n";
import { detectTimeZone } from "@/lib/time";
import { legalPath } from "@/product/legal/links";
import { SkeletonCards } from "@/product/shared/States";
import { AccountShell, Notice, SideLink, accountButton, accountInput } from "./AccountShell";
import { NewPassword } from "./NewPassword";
import { stepError } from "./stepError";

type Sent = "idle" | "sent";

export function RegisterPage() {
  const { locale } = useI18n();
  const boxes = useQuery({
    queryKey: ["auth", "signup", "consents", locale],
    queryFn: () => v1.signupConsents(locale),
    retry: false,
    staleTime: 60_000,
  });
  const closed = boxes.error instanceof LiveApiError && boxes.error.status === 404;
  const purposes = boxes.data?.purposes ?? [];

  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [repeat, setRepeat] = useState("");
  const [ticked, setTicked] = useState<ReadonlySet<ConsentKind>>(new Set());
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [state, setState] = useState<Sent>("idle");
  const [resent, setResent] = useState<"idle" | "busy" | "sent" | "failed">("idle");
  const zone = useMemo(detectTimeZone, []);

  const everyBox = purposes.length > 0 && purposes.every((p) => ticked.has(p.kind));
  const ready =
    firstName.trim() !== "" &&
    lastName.trim() !== "" &&
    email.trim() !== "" &&
    phone.trim() !== "" &&
    nickname.trim() !== "" &&
    passwordReady(password, repeat, { email: email.trim(), name: nickname.trim() }) &&
    everyBox;

  function toggle(kind: ConsentKind, on: boolean) {
    setTicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(kind);
      else next.delete(kind);
      return next;
    });
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      await v1.signup({
        first_name: firstName,
        last_name: lastName,
        email: email.trim(),
        phone,
        nickname: nickname.trim(),
        password,
        language: locale as Language,
        timezone: zone,
        consents: purposes.map((p) => ({ kind: p.kind, granted: true, version: p.version })),
      });
      setPassword("");
      setRepeat("");
      setState("sent");
    } catch (err) {
      if (err instanceof LiveApiError && err.code === "legal_text_changed") {
        setTicked(new Set());
        setFailure(t("auth.signup.textChanged"));
        await boxes.refetch();
      } else {
        setFailure(stepError(err));
      }
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setResent("busy");
    try {
      await v1.resendVerification(email.trim());
      setResent("sent");
    } catch {
      setResent("failed");
    }
  }

  if (closed) {
    return (
      <AccountShell title={t("auth.signup.title")} testId="register-page">
        <Notice tone="info" testId="signup-closed">
          {t("auth.signup.closed")}
        </Notice>
        <p className="text-sm text-muted-foreground">{t("auth.signup.closedBody")}</p>
        <SideLink href="/login">{t("auth.account.toLoginNow")}</SideLink>
      </AccountShell>
    );
  }

  if (state === "sent") {
    return (
      <AccountShell title={t("auth.signup.sentTitle")} testId="register-page">
        <Notice tone="ok" testId="signup-sent">
          {t("auth.signup.sent")}
        </Notice>
        <p className="text-sm text-muted-foreground">{t("auth.signup.sentNext")}</p>
        {resent === "sent" ? (
          <Notice tone="ok" testId="signup-resent">
            {t("auth.resendConfirmationSent")}
          </Notice>
        ) : (
          <button
            type="button"
            onClick={() => void resend()}
            disabled={resent === "busy"}
            className="tap-y relative flex w-full items-center justify-center gap-2 rounded-md border border-border-strong px-3 py-2 text-sm font-medium hover:bg-elevated"
            data-testid="signup-resend"
          >
            {resent === "busy" ? (
              <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
            ) : (
              <Mail aria-hidden className="h-4 w-4" />
            )}
            {t("auth.signup.resend")}
          </button>
        )}
        {resent === "failed" ? <Notice tone="error">{t("errors.generic")}</Notice> : null}
        <SideLink href="/login">{t("auth.account.toLoginNow")}</SideLink>
      </AccountShell>
    );
  }

  return (
    <AccountShell
      title={t("auth.signup.title")}
      subtitle={t("auth.signup.subtitle")}
      testId="register-page"
    >
      {boxes.isPending ? (
        <SkeletonCards count={1} />
      ) : (
        <form
          onSubmit={(e) => void submit(e)}
          className="space-y-4"
          noValidate
          data-testid="register-form"
        >
          <div className="grid gap-4 min-[420px]:grid-cols-2">
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                {t("auth.signup.firstName")}
              </span>
              <input
                type="text"
                name="given-name"
                autoComplete="given-name"
                required
                maxLength={60}
                value={firstName}
                onChange={(e) => setFirstName(e.target.value)}
                className={accountInput}
                data-testid="signup-first-name"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                {t("auth.signup.lastName")}
              </span>
              <input
                type="text"
                name="family-name"
                autoComplete="family-name"
                required
                maxLength={60}
                value={lastName}
                onChange={(e) => setLastName(e.target.value)}
                className={accountInput}
                data-testid="signup-last-name"
              />
            </label>
          </div>
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">
              {t("auth.signup.email")}
            </span>
            <input
              type="email"
              name="email"
              autoComplete="username"
              inputMode="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={accountInput}
              data-testid="signup-email"
            />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">
              {t("auth.signup.phone")}
            </span>
            <input
              type="tel"
              name="tel"
              autoComplete="tel"
              inputMode="tel"
              required
              maxLength={40}
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              aria-describedby="signup-phone-hint"
              className={accountInput}
              data-testid="signup-phone"
            />
            <span id="signup-phone-hint" className="mt-1 block text-xs text-muted-foreground">
              {t("auth.signup.phoneHint")}
            </span>
          </label>
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">
              {t("auth.signup.nickname")}
            </span>
            <input
              type="text"
              name="nickname"
              autoComplete="nickname"
              required
              maxLength={24}
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              aria-describedby="signup-nickname-hint"
              className={accountInput}
              data-testid="signup-nickname"
            />
            <span id="signup-nickname-hint" className="mt-1 block text-xs text-muted-foreground">
              {t("auth.signup.nicknameHint")}
            </span>
          </label>
          <NewPassword
            hideEmail
            email={email.trim()}
            name={nickname.trim()}
            value={password}
            onChange={setPassword}
            repeat={repeat}
            onRepeat={setRepeat}
          />
          <fieldset className="space-y-3" data-testid="signup-consents">
            <legend className="text-sm font-semibold">{t("auth.signup.consentsTitle")}</legend>
            <p className="text-xs text-muted-foreground">{t("auth.signup.consentsIntro")}</p>
            {purposes.map((p) => (
              <div key={p.kind} className="rounded-md border border-border p-3">
                <label className="flex min-h-11 cursor-pointer items-start gap-3 text-sm leading-relaxed">
                  <input
                    type="checkbox"
                    name={p.kind}
                    data-testid={`signup-consent-${p.kind}`}
                    checked={ticked.has(p.kind)}
                    onChange={(e) => toggle(p.kind, e.currentTarget.checked)}
                    className="mt-0.5 h-5 w-5 shrink-0 accent-primary"
                  />
                  <span>{p.statement}</span>
                </label>
                <a
                  href={legalPath(p.document)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="tap-y relative ml-8 inline-block text-xs text-primary underline-offset-2 hover:underline"
                >
                  {t("auth.signup.read", { document: t(`legal.doc.${p.document}`) })}
                </a>
              </div>
            ))}
          </fieldset>
          {failure ? (
            <Notice tone="error" testId="signup-error">
              {failure}
            </Notice>
          ) : null}
          <button
            type="submit"
            disabled={!ready || busy}
            className={accountButton}
            data-testid="signup-submit"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
            {busy ? t("auth.signup.submitting") : t("auth.signup.submit")}
          </button>
        </form>
      )}
      <SideLink href="/login">{t("auth.signup.haveAccount")}</SideLink>
    </AccountShell>
  );
}
