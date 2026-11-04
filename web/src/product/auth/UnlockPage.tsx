/**
 * /unlock (plan UX, A7): the e-mail's link to lift the wait of an account locked after failed sign-ins, valid one
 * hour and once. Nothing happens on opening the page - a mail scanner that follows links unlocks nothing -, only on
 * the reader's tap.
 */
import { useEffect, useState } from "react";
import { Loader2, Unlock } from "lucide-react";
import { forgetLinkFromAddress, readLinkToken } from "@/lib/auth/linkToken";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { t } from "@/lib/i18n";
import { AccountShell, Notice, SideLink, accountButton } from "./AccountShell";
import { stepError } from "./stepError";

export function UnlockPage() {
  const [token] = useState(() => readLinkToken());
  useEffect(() => forgetLinkFromAddress(), []);
  const [state, setState] = useState<"idle" | "busy" | "done" | "invalid" | "off">(
    token ? "idle" : "invalid",
  );
  const [failure, setFailure] = useState<string | null>(null);

  async function unlock() {
    if (!token) return;
    setState("busy");
    setFailure(null);
    try {
      await v1.unlock(token);
      setState("done");
    } catch (err) {
      if (err instanceof LiveApiError && err.status === 410) setState("invalid");
      else if (err instanceof LiveApiError && err.status === 404) setState("off");
      else {
        setFailure(stepError(err));
        setState("idle");
      }
    }
  }

  return (
    <AccountShell title={t("auth.account.unlockTitle")} testId="unlock-page">
      {state === "done" ? (
        <>
          <Notice tone="ok" testId="unlock-done">
            {t("auth.account.unlockDone")}
          </Notice>
          <a href="/login" className={accountButton} data-testid="unlock-to-login">
            {t("auth.account.toLoginNow")}
          </a>
        </>
      ) : state === "invalid" ? (
        <>
          <Notice tone="warning" testId="link-invalid">
            {t("auth.account.unlockInvalid")}
          </Notice>
          <SideLink href="/login">{t("auth.account.toLogin")}</SideLink>
        </>
      ) : state === "off" ? (
        <>
          <Notice tone="info" testId="self-service-off">
            {t("auth.account.off")}
          </Notice>
          <SideLink href="/login">{t("auth.account.toLogin")}</SideLink>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">{t("auth.account.unlockBody")}</p>
          {failure ? <Notice tone="error">{failure}</Notice> : null}
          <button
            type="button"
            onClick={() => void unlock()}
            disabled={state === "busy"}
            className={accountButton}
            data-testid="unlock-submit"
          >
            {state === "busy" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Unlock className="h-4 w-4" />
            )}
            {t("auth.account.unlockSubmit")}
          </button>
        </>
      )}
    </AccountShell>
  );
}
