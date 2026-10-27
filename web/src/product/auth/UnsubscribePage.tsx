/**
 * /unsubscribe (plan UX, B8; section 33): the weekly summary's link to leave it, in every summary, for a year. Nothing
 * happens on opening the page - a mail scanner that follows links leaves nobody -, only on the reader's tap; no session
 * is needed and the page opens nothing of the account. The mail client's own one-click button (RFC 8058) does not come
 * here: it posts straight to the API.
 */
import { useEffect, useState } from "react";
import { Loader2, MailX } from "lucide-react";
import { forgetLinkFromAddress, readLinkToken } from "@/lib/auth/linkToken";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { t } from "@/lib/i18n";
import { AccountShell, Notice, SideLink, accountButton } from "./AccountShell";
import { stepError } from "./stepError";

export function UnsubscribePage() {
  const [token] = useState(() => readLinkToken());
  useEffect(() => forgetLinkFromAddress(), []);
  const [state, setState] = useState<"idle" | "busy" | "done" | "already" | "invalid">(
    token ? "idle" : "invalid",
  );
  const [failure, setFailure] = useState<string | null>(null);

  async function leave() {
    if (!token) return;
    setState("busy");
    setFailure(null);
    try {
      const result = await v1.leaveWeeklySummary(token);
      setState(result.left ? "done" : "already");
    } catch (err) {
      if (err instanceof LiveApiError && (err.status === 400 || err.status === 422)) {
        setState("invalid");
      } else {
        setFailure(stepError(err));
        setState("idle");
      }
    }
  }

  return (
    <AccountShell title={t("auth.account.unsubscribeTitle")} testId="unsubscribe-page">
      {state === "done" || state === "already" ? (
        <>
          <Notice tone="ok" testId={state === "done" ? "unsubscribe-done" : "unsubscribe-already"}>
            {t(
              state === "done" ? "auth.account.unsubscribeDone" : "auth.account.unsubscribeAlready",
            )}
          </Notice>
          <SideLink href="/profile#notifications">{t("auth.account.unsubscribeProfile")}</SideLink>
        </>
      ) : state === "invalid" ? (
        <>
          <Notice tone="warning" testId="link-invalid">
            {t("auth.account.unsubscribeInvalid")}
          </Notice>
          <SideLink href="/profile#notifications">{t("auth.account.unsubscribeProfile")}</SideLink>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">{t("auth.account.unsubscribeBody")}</p>
          {failure ? <Notice tone="error">{failure}</Notice> : null}
          <button
            type="button"
            onClick={() => void leave()}
            disabled={state === "busy"}
            className={accountButton}
            data-testid="unsubscribe-submit"
          >
            {state === "busy" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <MailX className="h-4 w-4" />
            )}
            {t("auth.account.unsubscribeSubmit")}
          </button>
        </>
      )}
    </AccountShell>
  );
}
