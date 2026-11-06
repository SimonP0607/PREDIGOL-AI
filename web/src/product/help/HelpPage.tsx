/**
 * Ayuda (/help, plan UX, A14; section 32): the reader finds the answer alone or writes to PrediGol. 25 questions in ES
 * and EN by group with an accent-blind search (each one opens in place; /help#faq-renew opens that one), the reader's own
 * messages with their state, the glossary, the optional five-step tour (A13 started it from the glossary until this page
 * existed), «Juego responsable», «Privacidad y datos», and the contact: «Reportar un problema» and - once the owner has
 * given them - WhatsApp and an address. Reachable from the account menu (two taps from any screen), from every error and
 * with the membership ended or suspended (A8's limited paths). The two about the notices on the devices (B7) only while
 * the owner made notices available.
 */
import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import {
  BookOpen,
  ChevronRight,
  Compass,
  HeartHandshake,
  LifeBuoy,
  Mail,
  MessageCircle,
  Search,
  ShieldCheck,
} from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { ContactChannel, SupportContact, SupportTicket } from "@/lib/api/v1/types_support";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { WhatsappLink } from "@/product/support/WhatsappLink";
import { Card, PageTitle } from "@/product/shared/States";
import { usePush } from "@/product/push/usePush";
import { useReportProblem } from "@/product/support/report";
import { TourStart } from "@/product/tour/Tour";
import { HOW_PATH } from "./howItWorks";
import {
  FAQ_GROUPS,
  FAQ_IDS,
  FAQ_LINKS,
  FAQ_NEEDS_PUSH,
  faqAnchor,
  faqAnswer,
  faqMatches,
  faqQuestion,
  type FaqId,
} from "./faq";

const linkClass =
  "tap-y relative inline-flex min-h-11 items-center gap-2 rounded-md border border-border-strong px-3 text-sm font-medium hover:bg-elevated";

/** A link inside the app, its path and its anchor apart (the router wants them so). */
function AppLink({
  to,
  children,
  className,
}: {
  to: string;
  children: ReactNode;
  className?: string | undefined;
}) {
  const [path, hash] = to.split("#");
  return (
    <Link to={(path || "/") as never} {...(hash ? { hash } : {})} className={className}>
      {children}
    </Link>
  );
}

export function ReportButton({ className }: { className?: string }) {
  const report = useReportProblem();
  if (!report.available) return null;
  return (
    <button
      type="button"
      onClick={() => report.open()}
      data-testid="help-report"
      className={cn(
        "inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground",
        className,
      )}
    >
      <LifeBuoy aria-hidden className="h-4 w-4" />
      {t("support.help.contact.report")}
    </button>
  );
}

export function HelpPage() {
  const state = useQuery(live.support);
  const push = usePush();
  const hash = useRouterState({ select: (s) => s.location.hash.replace(/^#/, "") });
  const [query, setQuery] = useState("");
  const searching = query.trim().length > 0;
  const pushOn = push.available;
  const shown = useMemo(
    () =>
      new Set(FAQ_IDS.filter((id) => (pushOn || !FAQ_NEEDS_PUSH.has(id)) && faqMatches(id, query))),
    [query, pushOn],
  );
  const groups = FAQ_GROUPS.map(
    (g) => [g.id, g.items.filter((id) => shown.has(id))] as const,
  ).filter(([, items]) => items.length > 0);
  const enabled = state.data?.enabled ?? true;
  const tickets = state.data?.tickets ?? [];
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="help-page">
      <PageTitle
        title={t("support.help.title")}
        subtitle={t("support.help.subtitle")}
        right={enabled ? <ReportButton /> : null}
      />
      {tickets.length > 0 ? <MyTickets tickets={tickets} readOnly={!enabled} /> : null}
      <div className="sticky top-sticky z-10 -mx-1 bg-background/95 px-1 py-2 backdrop-blur">
        <label className="relative block">
          <span className="sr-only">{t("support.help.searchLabel")}</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("support.help.searchPlaceholder")}
            data-testid="help-search"
            className="h-11 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
          />
        </label>
        <p className="mt-1.5 text-caption text-subtle-foreground" aria-live="polite">
          {searching
            ? shown.size === 0
              ? t("support.help.noResults", { q: query.trim() })
              : t("support.help.results", { count: shown.size })
            : null}
        </p>
      </div>
      {groups.map(([group, items]) => (
        <section key={group} aria-labelledby={`help-${group}`} className="flex flex-col gap-2">
          <h2 id={`help-${group}`} className="font-display text-lg font-semibold tracking-tight">
            {t(`support.help.groups.${group}`)}
          </h2>
          <div className="flex flex-col gap-2">
            {items.map((id) => (
              <Question
                key={`${id}-${searching ? "found" : "all"}`}
                id={id}
                open={searching || hash === faqAnchor(id)}
              />
            ))}
          </div>
        </section>
      ))}
      <MoreHelp />
      <Contact contact={state.data?.contact ?? null} enabled={enabled} />
    </div>
  );
}

function Question({ id, open }: { id: FaqId; open: boolean }) {
  const link = FAQ_LINKS[id];
  return (
    <details
      id={faqAnchor(id)}
      open={open || undefined}
      data-testid="help-question"
      data-faq={id}
      className="group scroll-mt-[calc(var(--app-sticky-top,4rem)+5.5rem)] rounded-xl border border-border bg-card"
    >
      <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between gap-3 rounded-xl px-4 py-3 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <span>{faqQuestion(id)}</span>
        <ChevronRight
          aria-hidden
          className="h-4 w-4 shrink-0 text-subtle-foreground transition-transform group-open:rotate-90"
        />
      </summary>
      <div className="px-4 pb-4">
        <p className="text-sm leading-relaxed text-muted-foreground">{faqAnswer(id)}</p>
        {link ? (
          <AppLink
            to={link.to}
            className="tap-y relative mt-2 inline-flex min-h-6 items-center gap-1 text-sm font-medium text-primary underline-offset-4 hover:underline"
          >
            {t(`support.help.go.${link.label}`)}
            <ChevronRight aria-hidden className="h-3.5 w-3.5" />
          </AppLink>
        ) : null}
      </div>
    </details>
  );
}

function MyTickets({ tickets, readOnly }: { tickets: SupportTicket[]; readOnly: boolean }) {
  return (
    <Card className="p-4" id="tickets">
      <section
        aria-labelledby="help-tickets"
        className="flex flex-col gap-3"
        data-testid="help-tickets"
      >
        <h2 id="help-tickets" className="font-display text-base font-semibold">
          {t("support.help.tickets.title")}
        </h2>
        {readOnly ? (
          <p className="text-caption text-muted-foreground">{t("support.help.tickets.readOnly")}</p>
        ) : null}
        <ul className="flex flex-col divide-y divide-border">
          {tickets.map((ticket) => (
            <li key={ticket.id}>
              <Link
                to="/help/messages/$ticketId"
                params={{ ticketId: String(ticket.id) }}
                data-testid={`help-ticket-${ticket.id}`}
                className="flex min-h-12 items-center justify-between gap-3 py-2 hover:text-primary"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">
                    {t(`support.report.category.${ticket.category}.label`)}
                  </span>
                  <span className="block text-caption text-muted-foreground">
                    {t("support.help.tickets.number", { id: ticket.id })} ·{" "}
                    {formatDateTime(ticket.opened_at)}
                  </span>
                </span>
                <span
                  className={cn(
                    "shrink-0 rounded-full px-2 py-0.5 text-caption font-medium",
                    ticket.status === "answered"
                      ? "bg-primary/15 text-primary"
                      : ticket.status === "open"
                        ? "bg-warning/15 text-warning"
                        : "bg-muted text-muted-foreground",
                  )}
                >
                  {t(`support.help.tickets.status.${ticket.status}`)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </section>
    </Card>
  );
}

function MoreHelp() {
  return (
    <section aria-labelledby="help-more" className="flex flex-col gap-3">
      <h2 id="help-more" className="font-display text-lg font-semibold tracking-tight">
        {t("support.help.more.title")}
      </h2>
      <div className="grid gap-2 sm:grid-cols-2">
        <MoreCard
          to={HOW_PATH}
          icon={<Compass aria-hidden className="h-4 w-4 text-primary" />}
          title={t("support.help.more.howItWorks")}
          body={t("support.help.more.howItWorksBody")}
          testId="help-how-it-works"
        />
        <MoreCard
          to="/help/glossary"
          icon={<BookOpen aria-hidden className="h-4 w-4 text-primary" />}
          title={t("support.help.more.glossary")}
          body={t("support.help.more.glossaryBody")}
          testId="help-glossary"
        />
        <MoreCard
          to="/legal/responsible-gaming"
          icon={<HeartHandshake aria-hidden className="h-4 w-4 text-primary" />}
          title={t("support.help.more.responsible")}
          body={t("support.help.more.responsibleBody")}
        />
        <MoreCard
          to="/profile#privacy"
          icon={<ShieldCheck aria-hidden className="h-4 w-4 text-primary" />}
          title={t("support.help.more.privacy")}
          body={t("support.help.more.privacyBody")}
        />
      </div>
      {/* Plan UX, A13: the optional five-step tour starts from the help. */}
      <TourStart />
    </section>
  );
}

function MoreCard({
  to,
  icon,
  title,
  body,
  testId,
}: {
  to: string;
  icon: ReactNode;
  title: string;
  body: string;
  testId?: string;
}) {
  return (
    <AppLink
      to={to}
      className="flex min-h-16 items-start gap-3 rounded-xl border border-border bg-card p-3 hover:bg-elevated"
    >
      <span className="mt-0.5">{icon}</span>
      <span className="min-w-0" data-testid={testId}>
        <span className="block text-sm font-medium">{title}</span>
        <span className="block text-caption text-muted-foreground">{body}</span>
      </span>
    </AppLink>
  );
}

const DEFAULT_ORDER: readonly ContactChannel[] = ["tickets", "whatsapp", "email"];

function Contact({ contact, enabled }: { contact: SupportContact | null; enabled: boolean }) {
  const report = useReportProblem();
  const canReport = enabled && report.available;
  const whatsapp = contact?.whatsapp ?? null;
  const email = contact?.email ?? null;
  const hours = contact?.hours ?? null;
  // The owner's order (FBI_SUPPORT_CHANNELS); an older answer without it keeps the old one: report, WhatsApp, e-mail.
  const order = contact?.channels?.length ? contact.channels : DEFAULT_ORDER;
  const channels: Record<ContactChannel, ReactNode> = {
    tickets: canReport ? <ReportButton key="tickets" /> : null,
    whatsapp: whatsapp ? (
      <WhatsappLink
        key="whatsapp"
        digits={whatsapp}
        text={t("support.help.contact.whatsappText")}
        className={linkClass}
        testId="help-whatsapp"
      >
        <MessageCircle aria-hidden className="h-4 w-4" />
        {t("support.help.contact.whatsapp")}
      </WhatsappLink>
    ) : null,
    email: email ? (
      <a key="email" href={`mailto:${email}`} className={linkClass} data-testid="help-email">
        <Mail aria-hidden className="h-4 w-4" />
        {t("support.help.contact.email")}
      </a>
    ) : null,
  };
  return (
    <Card className="p-4" id="contact">
      <section
        aria-labelledby="help-contact"
        className="flex flex-col gap-3"
        data-testid="help-contact"
      >
        <h2 id="help-contact" className="font-display text-base font-semibold">
          {t("support.help.contact.title")}
        </h2>
        <p className="text-sm text-muted-foreground">
          {canReport
            ? t("support.help.contact.body")
            : whatsapp || email
              ? t("support.help.contact.off")
              : t("support.help.contact.nothing")}
        </p>
        {canReport ? (
          <p className="text-caption text-muted-foreground">{t("support.help.contact.urgent")}</p>
        ) : null}
        <div className="flex flex-wrap gap-2">{order.map((channel) => channels[channel])}</div>
        {hours ? (
          <p className="text-caption text-muted-foreground" data-testid="help-hours">
            {t("support.help.contact.hours", { hours })}
          </p>
        ) : null}
      </section>
    </Card>
  );
}
