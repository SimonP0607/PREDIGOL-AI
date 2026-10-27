/**
 * The weekly summary by e-mail, in the reader's notifications (plan UX, B8; section 33): asked for apart - a switch
 * that starts off and carries the sentence of the processing policy the decision records -, left here or in one click
 * from any summary. The API lists the purpose only while the summary can really reach the reader (its switch, the
 * e-mail and its own sender), or to leave it: otherwise there is nothing to show, and nothing is shown.
 */
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Newspaper } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { ConsentPurpose } from "@/lib/api/v1/types_customer";
import { t, useI18n } from "@/lib/i18n";
import { track } from "@/lib/track";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { errorMessage } from "@/product/shared/States";
import { type DigestState, digestOf } from "./consents";

export function DigestView({
  digest,
  busy,
  failure,
  onToggle,
}: {
  digest: DigestState;
  busy: boolean;
  failure: string | null;
  onToggle: () => void;
}) {
  const { purpose, latest } = digest;
  const on = latest?.granted === true;
  return (
    <section className="space-y-2" data-testid="digest">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        <Newspaper aria-hidden className="h-4 w-4 text-primary" />
        {t("profile.notifications.digest.title")}
      </h3>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        disabled={busy}
        onClick={onToggle}
        data-testid="digest-switch"
        className="flex min-h-11 w-full items-center justify-between gap-3 rounded-md py-2 text-left hover:bg-elevated/60 disabled:opacity-60"
      >
        <span className="min-w-0 space-y-0.5">
          <span className="block text-sm">{purpose.statement}</span>
          <span className="block text-xs text-muted-foreground">
            {t("profile.notifications.digest.help")}
          </span>
          {latest ? (
            <span className="block text-caption text-muted-foreground" data-testid="digest-since">
              {t(
                latest.granted
                  ? "profile.notifications.digest.since"
                  : "profile.notifications.digest.left",
                {
                  date: formatDateTime(latest.at),
                },
              )}
            </span>
          ) : null}
        </span>
        <span className="flex shrink-0 items-center gap-2">
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          <span className="sr-only">
            {on ? t("profile.notifications.on") : t("profile.notifications.off")}
          </span>
          <span
            aria-hidden
            className={cn(
              "relative inline-flex h-6 w-11 items-center rounded-full border-2 border-transparent transition-colors",
              on ? "bg-primary" : "bg-input",
            )}
          >
            <span
              className={cn(
                "block h-5 w-5 rounded-full bg-background shadow transition-transform",
                on ? "translate-x-5" : "translate-x-0",
              )}
            />
          </span>
        </span>
      </button>
      {failure ? (
        <p role="alert" className="text-xs text-negative">
          {failure}
        </p>
      ) : null}
    </section>
  );
}

export function DigestSection() {
  const qc = useQueryClient();
  const { locale } = useI18n();
  const state = useQuery({
    queryKey: ["me", "consents", locale],
    queryFn: () => v1.myConsents(locale),
  });
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const digest = digestOf(state.data);
  // Not offered - or the consents could not be read: the e-mails above say what arrives, and Privacy shows the error.
  if (!digest) return null;
  const on = digest.latest?.granted === true;

  async function toggle(purpose: ConsentPurpose) {
    setBusy(true);
    setFailure(null);
    try {
      const next = await v1.decideConsents({
        decisions: [{ kind: purpose.kind, granted: !on, version: purpose.version }],
        locale,
        source: "profile",
      });
      qc.setQueryData(["me", "consents", locale], next);
      await qc.invalidateQueries({ queryKey: ["me", "consents"] });
      track(on ? "notification_disabled" : "notification_enabled", {
        channel: "email",
        category: "digest",
      });
    } catch (err) {
      setFailure(errorMessage(err));
      // the box the API no longer offers goes away (FBI_DIGEST switched off a minute ago)
      await qc.invalidateQueries({ queryKey: ["me", "consents"] });
    } finally {
      setBusy(false);
    }
  }

  return (
    <DigestView
      digest={digest}
      busy={busy}
      failure={failure}
      onToggle={() => void toggle(digest.purpose)}
    />
  );
}
