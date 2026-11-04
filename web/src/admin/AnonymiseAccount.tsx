/**
 * Deleting an account as anonymisation (plan UX, A7 and section 23): on a reader's deletion request, or to withdraw an
 * invitation nobody used. A dialog says what goes, what stays and that it cannot be undone; only the account's address
 * typed again lets it act (the server checks it as well). The result says what went, in counts, never in content.
 */
import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Trash2 } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { AdminAnonymised } from "@/lib/api/v1/types_auth";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/product/shared/States";

export function AnonymiseAccount({
  userId,
  email,
  invited = false,
  disabled = false,
  onDone,
  className,
}: {
  userId: number;
  email: string;
  /** Still invited: the button withdraws the invitation (the same anonymisation). */
  invited?: boolean;
  disabled?: boolean;
  onDone?: (result: AdminAnonymised) => void;
  className?: string;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const matches = typed.trim().toLowerCase() === email.trim().toLowerCase();

  function close() {
    setOpen(false);
    setTyped("");
    setError(null);
  }

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!matches || busy) return;
    setBusy(true);
    setError(null);
    try {
      const r = await v1.anonymiseUser(userId, typed.trim());
      close();
      onDone?.(r.data);
      await Promise.all([
        qc.invalidateQueries({ queryKey: live.users.queryKey }),
        qc.invalidateQueries({ queryKey: ["admin", "privacy-requests"] }),
      ]);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen(true)}
        data-testid={`anonymise-${userId}`}
        className={cn(
          "tap-y relative inline-flex items-center gap-1 rounded-md border border-negative/40 px-2 py-1 text-xs font-medium text-negative hover:bg-negative-soft disabled:opacity-50 pointer-coarse:px-2.5 pointer-coarse:py-2",
          className,
        )}
      >
        <Trash2 aria-hidden className="h-3 w-3" />
        {invited ? t("admin.users.withdrawInvite") : t("admin.users.anonymise")}
      </button>
      <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
        <DialogContent
          className="w-[calc(100%-2rem)] max-w-lg rounded-xl border-border bg-card"
          data-testid={`anonymise-dialog-${userId}`}
        >
          <DialogHeader>
            <DialogTitle className="break-all font-display">
              {t("admin.users.anonymiseTitle", { email })}
            </DialogTitle>
            <DialogDescription>{t("admin.users.anonymiseGoes")}</DialogDescription>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">{t("admin.users.anonymiseStays")}</p>
          <p className="text-sm font-semibold text-negative">
            {t("admin.users.anonymiseIrreversible")}
          </p>
          <form onSubmit={(e) => void submit(e)} className="space-y-3" noValidate>
            <label className="block">
              <span className="text-xs font-medium text-muted-foreground">
                {t("admin.users.anonymiseType")}
              </span>
              <input
                type="email"
                autoComplete="off"
                spellCheck={false}
                value={typed}
                onChange={(e) => setTyped(e.target.value)}
                className="mt-1 h-11 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none"
                data-testid={`anonymise-confirm-${userId}`}
              />
            </label>
            {error ? (
              <p role="alert" className="text-xs text-negative">
                {error}
              </p>
            ) : null}
            <div className="flex flex-wrap justify-end gap-2">
              <button
                type="button"
                onClick={close}
                className="tap-y relative h-11 rounded-md border border-border-strong px-4 text-sm hover:bg-elevated"
              >
                {t("common.cancel")}
              </button>
              <button
                type="submit"
                disabled={!matches || busy}
                className="tap-y relative inline-flex h-11 items-center gap-2 rounded-md bg-negative px-4 text-sm font-semibold text-white disabled:opacity-50"
                data-testid={`anonymise-ok-${userId}`}
              >
                {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
                {t("admin.users.anonymiseConfirm")}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
