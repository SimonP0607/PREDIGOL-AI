/**
 * Who asks, before another session of one's own account ends (plan UX, A7; ASVS 7.5.2 and R25 of the security plan):
 * the password, or a code from the authenticator app when the account has one. A stolen session alone cannot throw
 * the owner of the account out. A refusal stays in the dialog (wrong password, wrong code with the attempts left, the
 * wait); the dialog closes once the server agrees. Fields of 16 px: a phone does not zoom into them.
 */
import { useState, type FormEvent } from "react";
import { Loader2, LogOut } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { IdentityIn } from "@/lib/api/v1/types_auth";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { stepError } from "@/product/auth/stepError";

const input =
  "mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none";

export function IdentityDialog({
  open,
  onOpenChange,
  hasMfa,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The account has an authenticator app: a code from it is offered instead of the password. */
  hasMfa: boolean;
  /** Ends the session(s); a rejection is shown in the dialog. */
  onConfirm: (identity: IdentityIn) => Promise<unknown>;
}) {
  const [useCode, setUseCode] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setPassword("");
    setCode("");
    setError(null);
    setUseCode(false);
  }

  const digits = code.replace(/\D/g, "");
  const ready = useCode ? digits.length === 6 : password.length > 0;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!ready || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(useCode ? { code: digits } : { password });
      reset();
      onOpenChange(false);
    } catch (err) {
      setError(stepError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent
        className="w-[calc(100%-2rem)] max-w-md rounded-xl border-border bg-card"
        data-testid="identity-dialog"
      >
        <DialogHeader>
          <DialogTitle className="font-display">
            {t("profile.securityPanel.identity.title")}
          </DialogTitle>
          <DialogDescription>{t("profile.securityPanel.identity.body")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => void submit(e)} className="space-y-3" noValidate>
          {useCode ? (
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                {t("profile.securityPanel.identity.code")}
              </span>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={7}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))}
                className={cn(input, "numeric tracking-widest")}
                data-testid="identity-code"
              />
            </label>
          ) : (
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                {t("profile.securityPanel.identity.password")}
              </span>
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className={input}
                data-testid="identity-password"
              />
            </label>
          )}
          {hasMfa ? (
            <button
              type="button"
              onClick={() => {
                setUseCode((v) => !v);
                setError(null);
              }}
              className="tap-y relative text-xs font-medium text-primary"
              data-testid="identity-switch"
            >
              {useCode
                ? t("profile.securityPanel.identity.usePassword")
                : t("profile.securityPanel.identity.useCode")}
            </button>
          ) : null}
          {error ? (
            <p role="alert" className="text-xs text-negative" data-testid="identity-error">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap justify-end gap-2">
            <button
              type="button"
              onClick={() => {
                reset();
                onOpenChange(false);
              }}
              className="tap-y relative h-11 rounded-md border border-border-strong px-4 text-sm hover:bg-elevated"
            >
              {t("common.cancel")}
            </button>
            <button
              type="submit"
              disabled={!ready || busy}
              className="tap-y relative inline-flex h-11 items-center gap-2 rounded-md bg-negative px-4 text-sm font-semibold text-white disabled:opacity-50"
              data-testid="identity-confirm"
            >
              {busy ? (
                <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
              ) : (
                <LogOut aria-hidden className="h-4 w-4" />
              )}
              {t("profile.securityPanel.identity.confirm")}
            </button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
