/**
 * La ficha de un usuario (/admin/users/$userId, plan AP-A03, decisión D8): lo que antes eran dos pantallas - la cuenta
 * (Usuarios) y el cliente (Clientes) - en una sola, con cinco pestañas: Cuenta y acceso · Membresía y pagos · Soporte ·
 * Actividad y riesgo · Restricciones y auditoría. Cada acto de hoy sigue donde estaba, con el mismo permiso (solo el dueño
 * llega aquí) y queda en el registro de accesos con el usuario al que se refiere. No lleva IP, token ni clic suelto.
 */
import { useId, useState, type KeyboardEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";
import { PageHeader } from "@/components/layout/PageHeader";
import { LiveApiError, v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { AdminUser } from "@/lib/api/v1/types_auth";
import type { Customer } from "@/lib/api/v1/types_customers";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { t as tu } from "./userText";
import { formatDateTime, formatRelative } from "@/lib/time";
import { cn } from "@/lib/utils";
import { ErrorState, SkeletonCards } from "@/product/shared/States";
import {
  Consents,
  Export,
  Facts,
  Lifecycle,
  MembershipAction,
  Notes,
  Section,
  Tickets,
} from "./CustomerCard";
import { MembershipBadge } from "./CustomerParts";
import {
  RoleBadge,
  RowActions,
  SecurityActions,
  SecurityBadges,
  SessionsList,
  StatusDot,
} from "./UsersPage";

export const USER_TABS = ["account", "membership", "support", "activity", "restrictions"] as const;
export type UserTab = (typeof USER_TABS)[number];

function Tabs({ tab, onTab }: { tab: UserTab; onTab: (next: UserTab) => void }) {
  const base = useId();
  const move = (e: KeyboardEvent<HTMLButtonElement>) => {
    const at = USER_TABS.indexOf(tab);
    const next =
      e.key === "ArrowRight"
        ? USER_TABS[(at + 1) % USER_TABS.length]
        : e.key === "ArrowLeft"
          ? USER_TABS[(at + USER_TABS.length - 1) % USER_TABS.length]
          : e.key === "Home"
            ? USER_TABS[0]
            : e.key === "End"
              ? USER_TABS[USER_TABS.length - 1]
              : null;
    if (!next) return;
    e.preventDefault();
    onTab(next);
    document.getElementById(`${base}-${next}`)?.focus();
  };
  return (
    <div
      role="tablist"
      aria-label={tu("userfile.tabsLabel")}
      className="flex gap-1 overflow-x-auto border-b border-border"
      data-testid="user-tabs"
    >
      {USER_TABS.map((k) => (
        <button
          key={k}
          id={`${base}-${k}`}
          type="button"
          role="tab"
          aria-selected={tab === k}
          aria-controls={`${base}-panel`}
          tabIndex={tab === k ? 0 : -1}
          data-testid={`user-tab-${k}`}
          onKeyDown={move}
          onClick={() => onTab(k)}
          className={cn(
            "tap-y relative shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
            tab === k
              ? "border-primary text-foreground"
              : "border-transparent text-muted-foreground hover:text-foreground",
          )}
        >
          {tu(`userfile.tabs.${k}`)}
        </button>
      ))}
    </div>
  );
}

function Identity({ card }: { card: Customer }) {
  const who = card.identity;
  return (
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
  );
}

/** The account's own controls: role, active or not, invitation, deletion, security and open sessions (what «Usuarios» held). */
function AccountControls({
  user,
  self,
  onNotice,
}: {
  user: AdminUser;
  self: boolean;
  onNotice: (notice: string) => void;
}) {
  return (
    <Section id="access" title={tu("userfile.access")}>
      <div className="flex flex-wrap items-center gap-2">
        <RoleBadge role={user.role} />
        <StatusDot status={user.status} />
      </div>
      <SecurityBadges user={user} />
      <RowActions user={user} self={self} onNotice={onNotice} />
      <SecurityActions user={user} self={self} />
      <SessionsList user={user} />
    </Section>
  );
}

function Usage({ card }: { card: Customer }) {
  const { usage } = card;
  return (
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
  );
}

function Notifications({ card }: { card: Customer }) {
  const mail = card.notifications;
  return (
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
  );
}

function Feedback({ card }: { card: Customer }) {
  const { feedback } = card;
  return (
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
  );
}

function Membership({ card }: { card: Customer }) {
  return (
    <Section id="membership" title={t("admin.membership.column")}>
      <MembershipBadge membership={card.membership} />
      {card.suspended_reason ? (
        <p className="text-xs text-warning">{card.suspended_reason}</p>
      ) : null}
      {card.membership?.will_not_renew ? (
        <p className="text-xs text-muted-foreground">{t("admin.customers.willNotRenew")}</p>
      ) : null}
      <MembershipAction card={card} />
      <Link
        to="/admin/payments"
        className="tap-y relative inline-block text-sm font-medium text-primary hover:underline"
        data-testid="user-payments-link"
      >
        {tu("userfile.paymentsLink")}
      </Link>
    </Section>
  );
}

function Panel({
  tab,
  card,
  account,
  self,
  accountError,
  onNotice,
}: {
  tab: UserTab;
  card: Customer;
  account: AdminUser | null;
  self: boolean;
  accountError: boolean;
  onNotice: (notice: string) => void;
}) {
  switch (tab) {
    case "account":
      return (
        <div className="grid gap-4 lg:grid-cols-2">
          <Identity card={card} />
          {account ? (
            <AccountControls user={account} self={self} onNotice={onNotice} />
          ) : (
            <Section id="access" title={tu("userfile.access")}>
              <p className="text-xs text-muted-foreground">
                {accountError ? tu("userfile.accessError") : tu("userfile.accessLoading")}
              </p>
            </Section>
          )}
        </div>
      );
    case "membership":
      return (
        <div className="grid gap-4 lg:grid-cols-2">
          <Membership card={card} />
          <Lifecycle card={card} />
        </div>
      );
    case "support":
      return (
        <div className="grid gap-4 lg:grid-cols-2">
          <Tickets card={card} />
          <Notes card={card} />
          <Feedback card={card} />
        </div>
      );
    case "activity":
      return (
        <div className="grid gap-4 lg:grid-cols-2">
          <Usage card={card} />
          <Notifications card={card} />
        </div>
      );
    case "restrictions":
      return (
        <div className="space-y-4">
          <Consents card={card} />
          <Link
            to="/admin/audit"
            className="tap-y relative inline-block text-sm font-medium text-primary hover:underline"
            data-testid="user-audit-link"
          >
            {tu("userfile.auditLink")}
          </Link>
          <Export card={card} onNotice={onNotice} />
        </div>
      );
  }
}

function Body({ card }: { card: Customer }) {
  const auth = useAuth();
  const [tab, setTab] = useState<UserTab>("account");
  const [notice, setNotice] = useState<string | null>(null);
  const accounts = useQuery({ ...live.users });
  const account = accounts.data?.data.find((u) => u.id === card.identity.id) ?? null;
  const base = useId();
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
      <Tabs tab={tab} onTab={setTab} />
      <div id={`${base}-panel`} role="tabpanel" tabIndex={-1} data-testid={`user-panel-${tab}`}>
        <Panel
          tab={tab}
          card={card}
          account={account}
          self={card.identity.id === auth.user?.id}
          accountError={accounts.isError}
          onNotice={setNotice}
        />
      </div>
    </div>
  );
}

/** An owner's or the robot's account has no customer card (the API answers 404): its file is the account's controls alone. */
function AccountOnly({ userId }: { userId: number }) {
  const auth = useAuth();
  const [notice, setNotice] = useState<string | null>(null);
  const accounts = useQuery({ ...live.users });
  const user = accounts.data?.data.find((u) => u.id === userId) ?? null;
  if (accounts.isPending) return <SkeletonCards />;
  if (!user)
    return (
      <ErrorState
        error={accounts.error ?? new Error("not_found")}
        onRetry={() => void accounts.refetch()}
      />
    );
  return (
    <div className="space-y-4" data-testid="user-account-only">
      {notice ? (
        <p
          role="status"
          className="rounded-md border border-positive/40 bg-positive/10 px-3 py-2 text-sm text-positive"
        >
          {notice}
        </p>
      ) : null}
      <p className="text-sm text-muted-foreground">{tu("userfile.noCard")}</p>
      <AccountControls user={user} self={user.id === auth.user?.id} onNotice={setNotice} />
    </div>
  );
}

export function UserFile({ userId }: { userId: number }) {
  const q = useQuery({
    queryKey: ["v1", "admin", "customers", "card", userId],
    queryFn: () => v1.customer(userId),
    retry: (count, error) => !(error instanceof LiveApiError && error.status === 404) && count < 2,
  });
  const noCard = q.isError && q.error instanceof LiveApiError && q.error.status === 404;
  return (
    <div className="space-y-5">
      <PageHeader
        title={
          q.data?.identity.display_name ?? q.data?.identity.email ?? t("admin.pages.users.title")
        }
        description={q.data?.identity.email ?? ""}
        actions={
          <Link
            to="/admin/users"
            className="tap-y relative inline-flex items-center gap-1 text-sm font-medium text-primary"
          >
            <ArrowLeft aria-hidden className="h-4 w-4" />
            {tu("userfile.back")}
          </Link>
        }
      />
      {q.isPending ? (
        <SkeletonCards />
      ) : noCard ? (
        <AccountOnly userId={userId} />
      ) : q.isError ? (
        <ErrorState error={q.error} onRetry={() => void q.refetch()} />
      ) : (
        <Body card={q.data} />
      )}
    </div>
  );
}
