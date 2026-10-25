/**
 * The readers' privacy requests (plan UX, A4): queries, claims and deletion requests, open first by their legal
 * deadline in Colombian business days, with the thread and the owner's answer - a new status, or the one extension
 * the law allows (the answer says why and until when). Each answer is audited (an admin write).
 */
import { useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, ShieldQuestion } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { AdminPrivacyRequest, TicketStatus } from "@/lib/api/v1/types_customer";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, ErrorState, errorMessage } from "@/product/shared/States";
import { dayOf } from "@/product/legal/links";

function daysLeft(deadline: string): number {
  const end = Date.parse(`${deadline.slice(0, 10)}T23:59:59-05:00`);
  return Math.floor((end - Date.now()) / 86_400_000);
}

function Answer({ request }: { request: AdminPrivacyRequest }) {
  const qc = useQueryClient();
  const [body, setBody] = useState("");
  const [status, setStatus] = useState<TicketStatus>("answered");
  const [extend, setExtend] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    try {
      await v1.answerPrivacyRequest(request.id, { body: body.trim(), status, extend });
      setBody("");
      setExtend(false);
      await qc.invalidateQueries({ queryKey: ["admin", "privacy-requests"] });
    } catch (err) {
      setFailure(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => void submit(e)} className="space-y-2">
      <textarea
        value={body}
        rows={3}
        maxLength={4000}
        placeholder={t("legal.admin.answerPlaceholder")}
        onChange={(e) => setBody(e.target.value)}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:border-primary focus:outline-none"
      />
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs">
          {t("legal.admin.status")}
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as TicketStatus)}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm pointer-coarse:h-11"
          >
            {(["open", "answered", "closed"] as const).map((s) => (
              <option key={s} value={s}>
                {t(`legal.privacy.status.${s}`)}
              </option>
            ))}
          </select>
        </label>
        {request.extended_to === null ? (
          <label className="flex min-h-11 items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={extend}
              onChange={(e) => setExtend(e.currentTarget.checked)}
              className="h-4 w-4 accent-primary"
            />
            {t("legal.admin.extend")}
          </label>
        ) : null}
        <button
          type="submit"
          disabled={busy || !body.trim()}
          className="tap-y relative inline-flex h-9 items-center gap-2 rounded-md bg-primary px-3 text-sm font-semibold text-primary-foreground disabled:opacity-50 pointer-coarse:h-11"
        >
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {t("legal.admin.send")}
        </button>
      </div>
      {failure ? (
        <p role="alert" className="text-xs text-negative">
          {failure}
        </p>
      ) : null}
    </form>
  );
}

export function PrivacyRequestsCard() {
  const [all, setAll] = useState(false);
  const q = useQuery({
    queryKey: ["admin", "privacy-requests", all ? "all" : "open"],
    queryFn: () => v1.privacyRequests(all ? "all" : "open"),
  });
  return (
    <Card className="p-4">
      <div className="space-y-3" data-testid="admin-privacy-requests">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="flex items-center gap-2 font-display text-base font-semibold">
            <ShieldQuestion aria-hidden className="h-4 w-4 text-primary" />
            {t("legal.admin.title")}
          </h2>
          <button
            type="button"
            onClick={() => setAll((v) => !v)}
            className="tap-y relative rounded-md border border-border-strong px-3 py-1.5 text-xs hover:bg-elevated"
          >
            {all ? t("legal.admin.showOpen") : t("legal.admin.showAll")}
          </button>
        </div>
        <p className="text-xs text-muted-foreground">{t("legal.admin.help")}</p>
        {q.isPending ? (
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
        ) : q.isError ? (
          <ErrorState error={q.error} onRetry={() => void q.refetch()} />
        ) : q.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("legal.admin.empty")}</p>
        ) : (
          <ul className="space-y-3">
            {q.data.map((r) => {
              const left = r.deadline && r.status !== "closed" ? daysLeft(r.deadline) : null;
              return (
                <li
                  key={r.id}
                  className="space-y-2 rounded-md border border-border p-3"
                  data-testid={`privacy-request-${r.id}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{t(`legal.privacy.kind.${r.kind}`)}</div>
                      <div className="break-all text-caption text-muted-foreground">{r.email}</div>
                    </div>
                    <div className="text-right text-caption">
                      <div>{t(`legal.privacy.status.${r.status}`)}</div>
                      {r.deadline && r.status !== "closed" ? (
                        <div
                          className={cn(
                            "font-semibold",
                            left !== null && left < 0
                              ? "text-negative"
                              : left !== null && left <= 4
                                ? "text-warning"
                                : "text-foreground",
                          )}
                        >
                          {r.extended_to
                            ? t("legal.privacy.extended", { date: dayOf(r.extended_to) })
                            : t("legal.privacy.deadline", { date: dayOf(r.deadline) })}
                          {left !== null && left < 0 ? ` · ${t("legal.admin.overdue")}` : null}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  <ul className="space-y-1.5 border-l border-border pl-3">
                    {r.messages.map((m, i) => (
                      <li key={`${m.at}-${i}`} className="text-xs">
                        <span className="font-semibold">{t(`legal.admin.author.${m.author}`)}</span>
                        <span className="text-muted-foreground"> · {formatDateTime(m.at)}</span>
                        <p className="whitespace-pre-line break-words">{m.body}</p>
                      </li>
                    ))}
                  </ul>
                  {r.status !== "closed" ? <Answer request={r} /> : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}
