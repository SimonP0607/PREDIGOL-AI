/**
 * /forgot-password (plan UX, A7; R25 of the security plan): the reader's address, and always the same answer -
 * whether or not it has an account, whether or not an e-mail leaves. While the owner keeps self-service off, the page
 * says how to get back in instead (the owner gives a temporary password).
 */
import { SkeletonCards } from "@/product/shared/States";
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, Mail } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import { t } from "@/lib/i18n";
import { AccountShell, Notice, SideLink, accountButton, accountInput } from "./AccountShell";
import { stepError } from "./stepError";

export function ForgotPasswordPage() {
  const options = useQuery({
    queryKey: ["auth", "options"],
    queryFn: v1.accountOptions,
    staleTime: 60_000,
  });
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (busy || !email.trim()) return;
    setBusy(true);
    setFailure(null);
    try {
      await v1.forgotPassword(email.trim());
      setSent(true);
    } catch (err) {
      setFailure(stepError(err));
    } finally {
      setBusy(false);
    }
  }

  const off = options.data && !options.data.self_service;
  return (
    <AccountShell
      title={t("auth.account.forgotTitle")}
      subtitle={off ? undefined : t("auth.account.forgotSubtitle")}
      testId="forgot-page"
    >
      {options.isPending ? (
        <SkeletonCards count={1} />
      ) : off ? (
        <Notice tone="info" testId="self-service-off">
          {t("auth.account.forgotOff")}
        </Notice>
      ) : sent ? (
        <Notice tone="ok" testId="forgot-sent">
          {t("auth.account.forgotSent")}
        </Notice>
      ) : (
        <form
          onSubmit={(e) => void submit(e)}
          className="space-y-4"
          noValidate
          data-testid="forgot-form"
        >
          <label className="block">
            <span className="text-xs font-medium text-muted-foreground">{t("auth.email")}</span>
            <input
              type="email"
              name="email"
              autoComplete="username"
              inputMode="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={accountInput}
              data-testid="forgot-email"
            />
          </label>
          {failure ? <Notice tone="error">{failure}</Notice> : null}
          <button
            type="submit"
            disabled={busy || !email.trim()}
            className={accountButton}
            data-testid="forgot-submit"
          >
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
            {t("auth.account.forgotSubmit")}
          </button>
        </form>
      )}
      <SideLink href="/login" testId="to-login">
        {t("auth.account.toLogin")}
      </SideLink>
    </AccountShell>
  );
}
