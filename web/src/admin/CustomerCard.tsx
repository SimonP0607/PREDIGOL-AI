/**
 * La ficha de un cliente (/admin/customers/$userId, plan UX, B10): identity, status, membership, last access, use (counts of
 * days), notices, consents, tickets, answers and the owner's notes - and the acts the owner takes from it, each one in the
 * access trail with the reader it is about: renew or extend (the membership's dialog), activate or deactivate the account,
 * resend the invitation, read the consents' proof, review a ticket, leave a note and hand over a copy of the reader's data
 * (the owner's password first). The card holds no IP, no token and no loose click.
 */
import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft, CalendarPlus, Download, Loader2, Mail } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { v1 } from "@/lib/api/v1/client";
import type { Customer } from "@/lib/api/v1/types_customers";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t, translateOr } from "@/lib/i18n";
import { formatDateTime, formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { Card, ErrorState, SkeletonCards, errorMessage } from "@/product/shared/States";
import { MembershipBadge } from "./CustomerParts";
import { MembershipDialog } from "./MembershipDialog";

const BUTTON =
  "tap-y relative inline-flex h-9 items-center gap-2 rounded-md border border-border-strong px-3 text-sm font-medium hover:bg-elevated disabled:opacity-50 pointer-coarse:h-11";
const FIELD =
  "mt-1 h-10 w-full rounded-md border border-input bg-background px-3 text-base focus:border-primary focus:outline-none sm:text-sm";

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <Card className="space-y-3 p-4" data-testid={`customer-${id}`}>
      <h2 className="text-sm font-semibold">{title}</h2>
      {children}
    </Card>
  );
}

function Facts({ rows }: { rows: Array<[string, ReactNode]> }) {
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      {rows.map(([label, value]) => (
        <div key={label} className="min-w-0">
          <dt className="text-caption text-muted-foreground">{label}</dt>
          <dd className="numeric break-words">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

const labelOf = (group: string, key: string) => translateOr(`admin.customers.${group}.${key}`, key);

function Actions({ card, onNotice }: { card: Customer; onNotice: (text: string) => void }) {
  const qc = useQueryClient();
  const [membershipOpen, setMembershipOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = card.identity.id;
  const refresh = () => qc.invalidateQueries({ queryKey: ["v1", "admin", "customers"] });
  const status = useMutation({
    mutationFn: () =>
      v1.updateUser(id, { status: card.identity.status === "active" ? "disabled" : "active" }),
    onSuccess: () => {
      setConfirm(false);
      onNotice(t("admin.users.updated"));
      void refresh();
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const resend = useMutation({
    mutationFn: () => v1.resendInvitation(id),
    onSuccess: () => onNotice(t("admin.users.inviteResent")),
    onError: (e) => setError(errorMessage(e)),
  });
  const invited = card.identity.status === "invited";
  return (
    <div className="flex flex-wrap gap-2" data-testid="customer-actions">
      {!invited ? (
        <button
          type="button"
          data-testid="customer-membership"
          onClick={() => setMembershipOpen(true)}
          className={BUTTON}
        >
          <CalendarPlus aria-hidden className="h-4 w-4" />
          {t("admin.customers.manageMembership")}
        </button>
      ) : (
        <button
          type="button"
          data-testid="customer-resend"
          disabled={resend.isPending}
          onClick={() => resend.mutate()}
          className={BUTTON}
        >
          <Mail aria-hidden className="h-4 w-4" />
          {t("admin.users.resendInvite")}
        </button>
      )}
      {!invited ? (
        confirm ? (
          <>
            <button
              type="button"
              data-testid="customer-status-confirm"
              disabled={status.isPending}
              onClick={() => status.mutate()}
              className={cn(BUTTON, "border-negative/50 bg-negative-soft text-negative")}
            >
              {t("common.confirm")} ·{" "}
              {card.identity.status === "active"
                ? t("admin.users.deactivate")
                : t("admin.users.activate")}
            </button>
            <button type="button" onClick={() => setConfirm(false)} className={BUTTON}>
              {t("common.cancel")}
            </button>
          </>
        ) : (
          <button
            type="button"
            data-testid="customer-status"
            onClick={() => setConfirm(true)}
            className={BUTTON}
          >
            {card.identity.status === "active"
              ? t("admin.users.deactivate")
              : t("admin.users.activate")}
          </button>
        )
      ) : null}
      {error ? (
        <span role="alert" className="self-center text-caption text-negative">
          {error}
        </span>
      ) : null}
      <MembershipDialog
        userId={id}
        email={card.identity.email}
        open={membershipOpen}
        onOpenChange={(open) => {
          setMembershipOpen(open);
          if (!open) void refresh();
        }}
      />
    </div>
  );
}

function Consents({ card }: { card: Customer }) {
  const id = card.identity.id;
  const [proof, setProof] = useState(false);
  const q = useQuery({
    queryKey: ["v1", "admin", "customer-consents", id],
    queryFn: () => v1.customerConsents(id),
    enabled: proof,
    staleTime: 0,
    gcTime: 0,
  });
  return (
    <Section id="consents" title={t("admin.customers.consents")}>
      {card.consents.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("admin.customers.noConsents")}</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {card.consents.map((c) => (
            <li key={c.kind} className="flex flex-wrap items-center justify-between gap-2 py-2">
              <span>{labelOf("consentKinds", c.kind)}</span>
              <span className="numeric text-xs text-muted-foreground">
                {c.granted ? t("admin.customers.granted") : t("admin.customers.withdrawn")} · v
                {c.version} · {formatDateTime(c.at)}
              </span>
            </li>
          ))}
        </ul>
      )}
      {card.consents_due.length > 0 ? (
        <p className="text-xs text-warning">
          {t("admin.customers.consentsDue", { list: card.consents_due.join(", ") })}
        </p>
      ) : null}
      {proof ? (
        q.isPending ? (
          <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
        ) : q.isError ? (
          <p role="alert" className="text-xs text-negative">
            {errorMessage(q.error)}
          </p>
        ) : (
          <div className="overflow-x-auto" data-testid="customer-consent-proof">
            <table className="w-full min-w-[560px] text-xs">
              <thead className="text-left text-subtle-foreground">
                <tr>
                  <th className="py-1 pr-3 font-medium">{t("admin.customers.consentKind")}</th>
                  <th className="py-1 pr-3 font-medium">{t("admin.customers.decision")}</th>
                  <th className="py-1 pr-3 font-medium">{t("admin.customers.document")}</th>
                  <th className="py-1 pr-3 font-medium">{t("admin.customers.source")}</th>
                  <th className="py-1 font-medium">{t("admin.audit.when")}</th>
                </tr>
              </thead>
              <tbody>
                {(q.data?.data ?? []).map((c) => (
                  <tr key={`${c.kind}-${c.at}`} className="border-t border-border/60">
                    <td className="py-1 pr-3">{labelOf("consentKinds", c.kind)}</td>
                    <td className="py-1 pr-3">
                      {c.granted ? t("admin.customers.granted") : t("admin.customers.withdrawn")}
                    </td>
                    <td className="numeric py-1 pr-3" title={c.sha256}>
                      {c.document} v{c.version} · {c.locale} · {c.sha256.slice(0, 8)}
                    </td>
                    <td className="py-1 pr-3">{c.source}</td>
                    <td className="numeric py-1">{formatDateTime(c.at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        <>
          <button
            type="button"
            data-testid="customer-consent-open"
            onClick={() => setProof(true)}
            className={BUTTON}
          >
            {t("admin.customers.viewProof")}
          </button>
          <p className="text-caption text-muted-foreground">{t("admin.customers.recorded")}</p>
        </>
      )}
    </Section>
  );
}

function Tickets({ card }: { card: Customer }) {
  const id = card.identity.id;
  const [open, setOpen] = useState<number | null>(null);
  const q = useQuery({
    queryKey: ["v1", "admin", "customer-ticket", id, open],
    queryFn: () => v1.customerTicket(id, open as number),
    enabled: open !== null,
    staleTime: 0,
    gcTime: 0,
  });
  return (
    <Section id="tickets" title={t("admin.customers.tickets")}>
      {card.tickets.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("admin.customers.noTickets")}</p>
      ) : (
        <ul className="divide-y divide-border text-sm">
          {card.tickets.map((k) => (
            <li key={k.id} className="space-y-2 py-2" data-testid={`customer-ticket-${k.id}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span>
                  #{k.id} · {translateOr(`support.admin.category.${k.category}`, k.category)}
                </span>
                <span className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span className={cn(k.late && "font-semibold text-negative")}>
                    {t(`admin.customers.ticketStatus.${k.status}`)}
                    {k.late ? ` · ${t("admin.customers.late")}` : ""}
                  </span>
                  <span className="numeric">{formatRelative(k.opened_at)}</span>
                  <button
                    type="button"
                    data-testid={`customer-ticket-review-${k.id}`}
                    onClick={() => setOpen(open === k.id ? null : k.id)}
                    className="tap-y relative font-medium text-primary"
                  >
                    {open === k.id ? t("admin.customers.hide") : t("admin.customers.review")}
                  </button>
                </span>
              </div>
              {open === k.id ? (
                q.isPending ? (
                  <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
                ) : q.isError ? (
                  <p role="alert" className="text-xs text-negative">
                    {errorMessage(q.error)}
                  </p>
                ) : (
                  <ol className="space-y-2 rounded-md bg-elevated p-3 text-xs">
                    {q.data?.messages.map((m) => (
                      <li key={`${m.at}-${m.author}`}>
                        <span className="font-semibold">
                          {t(`admin.customers.author.${m.author}`)}
                        </span>{" "}
                        <span className="numeric text-muted-foreground">
                          {formatDateTime(m.at)}
                        </span>
                        <p className="mt-0.5 whitespace-pre-wrap break-words">{m.body}</p>
                      </li>
                    ))}
                  </ol>
                )
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {card.privacy_requests_open > 0 ? (
        <p className="text-xs text-warning">
          {t("admin.customers.privacyOpen", { count: card.privacy_requests_open })}
        </p>
      ) : null}
    </Section>
  );
}

function Notes({ card }: { card: Customer }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useMutation({
    mutationFn: () => v1.addCustomerNote(card.identity.id, text),
    onSuccess: () => {
      setText("");
      setError(null);
      void qc.invalidateQueries({ queryKey: ["v1", "admin", "customers"] });
    },
    onError: (e) => setError(errorMessage(e)),
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    add.mutate();
  };
  return (
    <Section id="notes" title={t("admin.customers.notes")}>
      <p className="text-caption text-muted-foreground">{t("admin.customers.notesHelp")}</p>
      <form onSubmit={submit} className="space-y-2">
        <label className="block text-xs text-muted-foreground">
          {t("admin.customers.newNote")}
          <textarea
            value={text}
            maxLength={500}
            rows={2}
            data-testid="customer-note-text"
            onChange={(e) => setText(e.target.value)}
            className={cn(FIELD, "h-auto py-2")}
          />
        </label>
        <button
          type="submit"
          data-testid="customer-note-save"
          disabled={add.isPending || text.trim().length < 3}
          className={BUTTON}
        >
          {add.isPending ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {t("admin.customers.saveNote")}
        </button>
        {error ? (
          <span role="alert" className="ml-2 text-caption text-negative">
            {error}
          </span>
        ) : null}
      </form>
      {card.notes.length > 0 ? (
        <ul className="divide-y divide-border text-sm" data-testid="customer-notes">
          {card.notes.map((n) => (
            <li key={n.id} className="py-2">
              <p className="whitespace-pre-wrap break-words">{n.note}</p>
              <p className="numeric text-caption text-muted-foreground">
                {n.author ?? "—"} · {formatDateTime(n.at)}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </Section>
  );
}

function download(doc: unknown, id: number) {
  const blob = new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `predigol-datos-${id}-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 10_000);
}

function Export({ card, onNotice }: { card: Customer; onNotice: (text: string) => void }) {
  const auth = useAuth();
  const needsCode = Boolean(auth.user?.mfa_enabled);
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const run = useMutation({
    mutationFn: () =>
      v1.exportCustomer(card.identity.id, { password, code: needsCode ? code : null }),
    onSuccess: (doc) => {
      download(doc, card.identity.id);
      setPassword("");
      setCode("");
      setOpen(false);
      onNotice(t("admin.customers.exported"));
    },
    onError: (e) => setError(errorMessage(e)),
  });
  return (
    <Section id="export" title={t("admin.customers.export")}>
      <p className="text-caption text-muted-foreground">{t("admin.customers.exportHelp")}</p>
      {open ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setError(null);
            run.mutate();
          }}
          className="space-y-3"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block text-xs text-muted-foreground">
              {t("admin.customers.yourPassword")}
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                data-testid="customer-export-password"
                onChange={(e) => setPassword(e.target.value)}
                className={FIELD}
              />
            </label>
            {needsCode ? (
              <label className="block text-xs text-muted-foreground">
                {t("admin.customers.yourCode")}
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  data-testid="customer-export-code"
                  onChange={(e) => setCode(e.target.value)}
                  className={FIELD}
                />
              </label>
            ) : null}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="submit"
              data-testid="customer-export-confirm"
              disabled={run.isPending || !password || (needsCode && code.length < 6)}
              className={cn(BUTTON, "bg-primary text-primary-foreground")}
            >
              {run.isPending ? (
                <Loader2 aria-hidden className="h-4 w-4 animate-spin" />
              ) : (
                <Download aria-hidden className="h-4 w-4" />
              )}
              {t("admin.customers.exportConfirm")}
            </button>
            <button type="button" onClick={() => setOpen(false)} className={BUTTON}>
              {t("common.cancel")}
            </button>
            {error ? (
              <span role="alert" className="text-caption text-negative">
                {error}
              </span>
            ) : null}
          </div>
        </form>
      ) : (
        <button
          type="button"
          data-testid="customer-export-start"
          onClick={() => setOpen(true)}
          className={BUTTON}
        >
          <Download aria-hidden className="h-4 w-4" />
          {t("admin.customers.exportButton")}
        </button>
      )}
    </Section>
  );
}

function Body({ card }: { card: Customer }) {
  const [notice, setNotice] = useState<string | null>(null);
  const { identity: who, usage, notifications: mail, feedback } = card;
  return (
    <div className="space-y-4">
      {notice ? (
        <p
          role="status"
          data-testid="customer-notice"
          className="rounded-md border border-positive/40 bg-positive/10 px-3 py-2 text-sm text-positive"
        >
          {notice}
        </p>
      ) : null}
      <Actions card={card} onNotice={setNotice} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Section id="identity" title={t("admin.customers.identity")}>
          <Facts
            rows={[
              [
                t("admin.users.email"),
                <span key="e" className="break-all">
                  {who.email}
                </span>,
              ],
              [t("admin.customers.alias"), who.display_name ?? "—"],
              [t("admin.users.status"), t(`admin.customers.status.${who.status}`)],
              [t("admin.users.language"), `${who.language.toUpperCase()} · ${who.timezone}`],
              [t("admin.users.created"), formatDateTime(who.created_at)],
              [
                t("admin.customers.lastSeen"),
                who.last_seen_at ? formatRelative(who.last_seen_at) : t("admin.users.never"),
              ],
              [
                t("admin.users.lastLogin"),
                who.last_login_at ? formatDateTime(who.last_login_at) : t("admin.users.never"),
              ],
              [
                t("admin.customers.security"),
                `${who.mfa_enabled ? "2FA" : t("admin.customers.noMfa")} · ${t("admin.customers.openSessions", { count: who.open_sessions })}`,
              ],
            ]}
          />
        </Section>
        <Section id="membership" title={t("admin.membership.column")}>
          <MembershipBadge membership={card.membership} />
          {card.suspended_reason ? (
            <p className="text-xs text-warning">{card.suspended_reason}</p>
          ) : null}
          {card.membership?.will_not_renew ? (
            <p className="text-xs text-muted-foreground">{t("admin.customers.willNotRenew")}</p>
          ) : null}
        </Section>
        <Section id="usage" title={t("admin.customers.usage")}>
          {usage.measured ? null : (
            <p className="text-xs text-warning">{t("admin.customers.notMeasured")}</p>
          )}
          <Facts
            rows={[
              [t("admin.customers.activeDays7"), `${usage.active_days_7}/7`],
              [t("admin.customers.activeDays30"), `${usage.active_days_30}/30`],
              [t("admin.customers.matches30"), usage.matches_viewed_30],
              [t("admin.customers.picksOpened30"), usage.picks_opened_30],
              [t("admin.customers.picksSaved"), usage.picks_saved],
              [t("admin.customers.parlaysSaved"), usage.parlays_saved],
              [t("admin.customers.errors24"), usage.errors_24h],
            ]}
          />
        </Section>
        <Section id="notifications" title={t("admin.customers.notifications")}>
          <Facts
            rows={[
              [
                t("admin.customers.emailStatus"),
                t(`admin.customers.emailStatuses.${mail.email_status}`),
              ],
              [
                t("admin.customers.emailOff"),
                mail.email_off.length ? mail.email_off.join(", ") : t("admin.customers.none"),
              ],
              [
                t("admin.customers.pushOff"),
                mail.push_off.length ? mail.push_off.join(", ") : t("admin.customers.none"),
              ],
              [
                t("admin.customers.emails30"),
                t("admin.customers.emailCounts", {
                  sent: mail.sent_30,
                  failed: mail.failed_30,
                  bounced: mail.bounced_30,
                  suppressed: mail.suppressed_30,
                }),
              ],
            ]}
          />
          <h3 className="text-xs font-semibold">{t("admin.customers.devices")}</h3>
          {mail.devices.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("admin.customers.noDevices")}</p>
          ) : (
            <ul className="text-xs" data-testid="customer-devices">
              {mail.devices.map((d) => (
                <li key={d.id} className="py-0.5">
                  {d.family} · {d.system}
                  {d.installed ? ` · ${t("admin.customers.installed")}` : ""} ·{" "}
                  {d.last_ok_at
                    ? t("admin.customers.lastOk", { when: formatRelative(d.last_ok_at) })
                    : t("admin.customers.neverOk")}
                </li>
              ))}
            </ul>
          )}
        </Section>
        <Consents card={card} />
        <Section id="feedback" title={t("admin.customers.feedback")}>
          <Facts
            rows={[
              [
                t("admin.customers.lastCsat"),
                feedback.last_csat !== null
                  ? `${feedback.last_csat}/5 · ${feedback.last_csat_at ? formatRelative(feedback.last_csat_at) : ""}`
                  : "—",
              ],
              [t("admin.customers.surveyAnswers"), feedback.survey_answers],
              [t("admin.customers.helpful"), `${feedback.helpful_yes} / ${feedback.helpful_no}`],
            ]}
          />
        </Section>
        <Tickets card={card} />
        <Notes card={card} />
      </div>
      <Export card={card} onNotice={setNotice} />
    </div>
  );
}

export function CustomerCard({ userId }: { userId: number }) {
  const q = useQuery({
    queryKey: ["v1", "admin", "customers", "card", userId],
    queryFn: () => v1.customer(userId),
  });
  return (
    <div className="space-y-5">
      <PageHeader
        title={
          q.data?.identity.display_name ??
          q.data?.identity.email ??
          t("admin.pages.customers.title")
        }
        description={q.data?.identity.email ?? ""}
        actions={
          <Link
            to="/admin/customers"
            className="tap-y relative inline-flex items-center gap-1 text-sm font-medium text-primary"
          >
            <ArrowLeft aria-hidden className="h-4 w-4" />
            {t("admin.customers.back")}
          </Link>
        }
      />
      {q.isPending ? (
        <SkeletonCards />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <Body card={q.data} />
      )}
    </div>
  );
}
