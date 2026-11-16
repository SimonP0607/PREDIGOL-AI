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
  Bell,
  BookOpen,
  ChevronRight,
  Compass,
  CreditCard,
  HeartHandshake,
  Inbox,
  KeyRound,
  LifeBuoy,
  Mail,
  MessageCircle,
  MessagesSquare,
  Receipt,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  type LucideIcon,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { fieldVariants } from "@/components/ui/field";
import { live } from "@/lib/api/v1/queries";
import type { ContactChannel, SupportContact, SupportTicket } from "@/lib/api/v1/types_support";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import { WhatsappLink } from "@/product/support/WhatsappLink";
import { Card, PageTitle } from "@/product/shared/States";
import { usePush } from "@/product/push/usePush";
import { useReportProblem } from "@/product/support/report";
import { GuidesPanel } from "@/product/guides/GuidesPanel";
import { AssistantSheet } from "./HelpAssistant";
import { TERM_KEYS } from "@/lib/glossary";
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
  type FaqGroup,
  type FaqId,
} from "./faq";

// the system's secondary button («Noche de partido», sheet 3) for the ways to reach PrediGol
const linkClass = buttonVariants({ variant: "secondary", size: "sm" });

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
      className={cn(buttonVariants({ variant: "primary", size: "sm" }), className)}
    >
      <LifeBuoy aria-hidden className="h-4 w-4" />
      {t("support.help.contact.report")}
    </button>
  );
}

/** Three common doubts, one tap from the search (sheet H01): each fills the search with its words. */
const QUICK_QUERIES = ["mail", "renew", "ev"] as const;

const GROUP_ICON: Record<FaqGroup, LucideIcon> = {
  start: Compass,
  account: KeyRound,
  membership: CreditCard,
  picks: Target,
  settlement: Receipt,
  notices: Bell,
  privacy: ShieldCheck,
  responsible: HeartHandshake,
};

export function HelpPage() {
  const state = useQuery(live.support);
  const push = usePush();
  const hash = useRouterState({ select: (s) => s.location.hash.replace(/^#/, "") });
  const [query, setQuery] = useState("");
  const [assistantOpen, setAssistantOpen] = useState(false);
  const searching = query.trim().length > 0;
  const pushOn = push.available;
  const visible = useMemo(
    () => FAQ_IDS.filter((id) => pushOn || !FAQ_NEEDS_PUSH.has(id)),
    [pushOn],
  );
  const shown = useMemo(
    () => new Set(visible.filter((id) => faqMatches(id, query))),
    [query, visible],
  );
  const groups = FAQ_GROUPS.map(
    (g) => [g.id, g.items.filter((id) => shown.has(id))] as const,
  ).filter(([, items]) => items.length > 0);
  const enabled = state.data?.enabled ?? true;
  const tickets = state.data?.tickets ?? [];
  const answered = tickets.filter((ticket) => ticket.status === "answered").length;
  const assistant = Boolean(state.data?.assistant);
  const whatsapp = state.data?.contact?.whatsapp ?? null;
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="help-page">
      <PageTitle title={t("support.help.heading")} subtitle={t("support.help.subtitle")} />
      {/* sheet H01: the search first, with three common doubts one tap away */}
      <div className="sticky top-sticky z-10 -mx-1 -mt-2 bg-background/95 px-1 py-2 backdrop-blur">
        <label className="relative block">
          <span className="sr-only">{t("support.help.searchLabel")}</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3.5 top-1/2 h-5 w-5 -translate-y-1/2 text-subtle-foreground"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("support.help.searchPlaceholder")}
            data-testid="help-search"
            className={cn(fieldVariants(), "h-13 pl-11 text-base sm:text-sm")}
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
      {!searching ? (
        <div className="-mt-3 flex flex-wrap gap-2" data-testid="help-quick">
          {QUICK_QUERIES.map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => setQuery(t(`support.help.quick.${k}.q`))}
              className="tap-y relative inline-flex min-h-8 items-center rounded-full border border-border bg-card px-3 text-[0.8125rem] font-semibold hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            >
              {t(`support.help.quick.${k}.label`)}
            </button>
          ))}
        </div>
      ) : null}
      {/* What a reader came to do (sheet H01): ask the assistant, talk to a person, report; then their messages. */}
      <HelpActions
        assistant={assistant}
        onAssistant={() => setAssistantOpen(true)}
        canReport={enabled}
      />
      {tickets.length > 0 ? (
        <a
          href="#tickets"
          className="tap-y card-surface relative flex min-h-16 items-center gap-3 rounded-card px-4 py-3 hover:bg-elevated"
          data-testid="help-action-tickets"
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-field bg-elevated">
            <Inbox aria-hidden className="h-5 w-5 text-primary" />
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">{t("support.help.tickets.title")}</span>
            <span className="block text-caption text-muted-foreground">
              {answered > 0
                ? t("support.help.actions.answered", { count: answered })
                : t("support.help.actions.tickets", { count: tickets.length })}
            </span>
          </span>
          {answered > 0 ? (
            <span className="numeric flex h-6 min-w-6 items-center justify-center rounded-full bg-gold px-1.5 text-xs font-bold text-gold-foreground">
              {answered}
            </span>
          ) : null}
          <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
        </a>
      ) : null}
      {enabled ? (
        <p className="-mt-2 text-caption text-muted-foreground">
          {t("support.help.contact.urgent")}
        </p>
      ) : null}
      {assistant ? (
        <AssistantSheet
          open={assistantOpen}
          onOpenChange={setAssistantOpen}
          faqShown={visible}
          whatsapp={whatsapp}
        />
      ) : null}
      <section aria-labelledby="help-faq" className="flex flex-col gap-2" data-testid="help-faq">
        <h2 id="help-faq" className="text-title">
          {t("support.help.faqTitle")}
        </h2>
        {groups.length === 0 ? null : (
          <div className="card-surface divide-y divide-border rounded-card">
            {groups.map(([group, items]) => {
              const Icon = GROUP_ICON[group];
              const open = searching || items.some((id) => hash === faqAnchor(id));
              return (
                <details
                  key={`${group}-${searching ? "found" : "all"}-${hash}`}
                  open={open || undefined}
                  className="group/faq"
                  data-testid="help-group"
                  data-group={group}
                >
                  <summary className="flex min-h-14 cursor-pointer list-none items-center gap-3 px-4 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-field bg-elevated">
                      <Icon aria-hidden className="h-[1.125rem] w-[1.125rem] text-primary" />
                    </span>
                    <h3 id={`help-${group}`} className="min-w-0 flex-1 text-sm font-semibold">
                      {t(`support.help.groups.${group}`)}
                    </h3>
                    <span className="numeric text-caption text-subtle-foreground">
                      {items.length}
                    </span>
                    <ChevronRight
                      aria-hidden
                      className="h-4 w-4 shrink-0 text-subtle-foreground transition-transform group-open/faq:rotate-90"
                    />
                  </summary>
                  <div className="flex flex-col gap-2 px-3 pb-3">
                    {items.map((id) => (
                      <Question
                        key={`${id}-${searching ? "found" : "all"}`}
                        id={id}
                        open={searching || hash === faqAnchor(id)}
                      />
                    ))}
                  </div>
                </details>
              );
            })}
          </div>
        )}
      </section>
      {tickets.length > 0 ? <MyTickets tickets={tickets} readOnly={!enabled} /> : null}
      <MoreHelp />
      <Contact contact={state.data?.contact ?? null} enabled={enabled} />
    </div>
  );
}

const ACTION_TILE =
  "tap-y motion-press card-surface relative flex min-h-[7.5rem] flex-col items-center justify-center gap-2 rounded-card px-2 py-3 text-center text-[0.8125rem] font-semibold leading-snug hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:text-sm";

/**
 * The three things a reader comes to Ayuda for, as tiles above everything else (sheet H01): the assistant (only while it
 * is on; it opens its conversation, sheet H02), a person (the channels, sheet H03) and a report (only while messages are
 * on; the sheet that already existed).
 */
function HelpActions({
  assistant,
  onAssistant,
  canReport,
}: {
  assistant: boolean;
  onAssistant: () => void;
  canReport: boolean;
}) {
  const report = useReportProblem();
  const icon = "flex h-11 w-11 shrink-0 items-center justify-center rounded-field";
  const reportOn = canReport && report.available;
  const count = 1 + (assistant ? 1 : 0) + (reportOn ? 1 : 0);
  return (
    <nav
      aria-label={t("support.help.actions.label")}
      data-testid="help-actions"
      className={cn(
        "grid gap-2",
        count === 3 ? "grid-cols-3" : count === 2 ? "grid-cols-2" : "grid-cols-1",
      )}
    >
      {assistant ? (
        <button
          type="button"
          onClick={onAssistant}
          className={ACTION_TILE}
          data-testid="help-action-assistant"
          aria-haspopup="dialog"
        >
          <span className={cn(icon, "bg-primary-soft")}>
            <Sparkles aria-hidden className="h-5 w-5 text-primary" />
          </span>
          <span>{t("support.help.actions.assistant")}</span>
          <span className="rounded-full bg-elevated px-2 py-0.5 text-micro font-bold uppercase tracking-wide text-muted-foreground">
            {t("support.help.actions.new")}
          </span>
        </button>
      ) : null}
      <a href="#contact" className={ACTION_TILE} data-testid="help-action-person">
        <span className={cn(icon, "bg-elevated")}>
          <MessagesSquare aria-hidden className="h-5 w-5 text-primary" />
        </span>
        <span>{t("support.help.actions.person")}</span>
      </a>
      {reportOn ? (
        <button
          type="button"
          onClick={() => report.open()}
          className={ACTION_TILE}
          data-testid="help-action-report"
        >
          <span className={cn(icon, "bg-gold-soft")}>
            <LifeBuoy aria-hidden className="h-5 w-5 text-gold" />
          </span>
          <span>{t("support.help.contact.report")}</span>
        </button>
      ) : null}
    </nav>
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
      className="card-surface group scroll-mt-[calc(var(--app-sticky-top,4rem)+5.5rem)] rounded-card"
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
  const tile =
    "tap-y relative flex min-h-28 flex-col justify-between gap-3 rounded-card border border-border bg-card p-4 hover:bg-elevated";
  const row = "flex min-h-16 items-center gap-3 px-4 py-3 hover:bg-elevated";
  return (
    <section aria-labelledby="help-more" className="flex flex-col gap-3">
      <h2 id="help-more" className="text-title">
        {t("support.help.more.title")}
      </h2>
      <div className="grid grid-cols-2 gap-2">
        <AppLink to={HOW_PATH} className={tile}>
          <span className="flex h-10 w-10 items-center justify-center rounded-field bg-elevated">
            <Compass aria-hidden className="h-5 w-5 text-primary" />
          </span>
          <span className="min-w-0" data-testid="help-how-it-works">
            <span className="block text-sm font-semibold">{t("support.help.more.howItWorks")}</span>
            <span className="block text-caption text-muted-foreground">
              {t("support.help.more.howItWorksShort")}
            </span>
          </span>
        </AppLink>
        <AppLink to="/help/glossary" className={tile}>
          <span className="flex h-10 w-10 items-center justify-center rounded-field bg-elevated">
            <BookOpen aria-hidden className="h-5 w-5 text-primary" />
          </span>
          <span className="min-w-0" data-testid="help-glossary">
            <span className="block text-sm font-semibold">{t("support.help.more.glossary")}</span>
            <span className="block text-caption text-muted-foreground">
              {t("support.help.more.glossaryCount", { count: TERM_KEYS.length })}
            </span>
          </span>
        </AppLink>
      </div>
      <div className="card-surface divide-y divide-border rounded-card">
        <AppLink to="/legal/responsible-gaming" className={row}>
          <HeartHandshake aria-hidden className="h-5 w-5 shrink-0 text-primary" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">
              {t("support.help.more.responsible")}
            </span>
            <span className="block text-caption text-muted-foreground">
              {t("support.help.more.responsibleBody")}
            </span>
          </span>
          <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
        </AppLink>
        <AppLink to="/profile#privacy" className={row}>
          <ShieldCheck aria-hidden className="h-5 w-5 shrink-0 text-primary" />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-semibold">{t("support.help.more.privacy")}</span>
            <span className="block text-caption text-muted-foreground">
              {t("support.help.more.privacyBody")}
            </span>
          </span>
          <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-subtle-foreground" />
        </AppLink>
      </div>
      {/* Plan UX-051: the guides (the welcome tour, the screens'), to see again, and the reader's own switch. */}
      <GuidesPanel className="mt-2" />
    </section>
  );
}

const DEFAULT_ORDER: readonly ContactChannel[] = ["tickets", "whatsapp", "email"];

function Channel({
  icon,
  tone,
  title,
  body,
  note,
  action,
  testId,
}: {
  icon: ReactNode;
  tone: string;
  title: ReactNode;
  body: string;
  note?: ReactNode;
  action: ReactNode;
  testId?: string;
}) {
  return (
    <li className="card-surface rounded-card p-4" data-testid={testId}>
      <div className="flex items-start gap-3">
        <span
          className={cn("flex h-11 w-11 shrink-0 items-center justify-center rounded-field", tone)}
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 text-sm font-semibold">{title}</p>
          <p className="text-caption text-muted-foreground">{body}</p>
        </div>
      </div>
      {note ? <div className="mt-2.5 text-caption text-muted-foreground">{note}</div> : null}
      <div className="mt-3 flex flex-wrap gap-2">{action}</div>
    </li>
  );
}

/**
 * «Hablar con una persona» (sheet H03): every channel the owner published, as a card that says what it is for - WhatsApp,
 * the Telegram channel (announcements only), the message in the app and the e-mail - then what to have at hand and the
 * warning that PrediGol never asks for a password. A channel the owner has not given is not drawn.
 */
function Contact({ contact, enabled }: { contact: SupportContact | null; enabled: boolean }) {
  const report = useReportProblem();
  const canReport = enabled && report.available;
  const whatsapp = contact?.whatsapp ?? null;
  const email = contact?.email ?? null;
  const hours = contact?.hours ?? null;
  // the official channel, announcements only (decision 6): the server gives the link only if it is a t.me address, and
  // the page checks it again before making it a link
  const telegram =
    contact?.telegram_url && contact.telegram_url.startsWith("https://t.me/")
      ? contact.telegram_url
      : null;
  // The owner's order (FBI_SUPPORT_CHANNELS); an older answer without it keeps the old one: report, WhatsApp, e-mail.
  const order = contact?.channels?.length ? contact.channels : DEFAULT_ORDER;
  const icon = "h-5 w-5";
  const channels: Record<ContactChannel, ReactNode> = {
    tickets: canReport ? (
      <Channel
        key="tickets"
        icon={<Inbox aria-hidden className={cn(icon, "text-primary")} />}
        tone="bg-elevated"
        title={t("support.help.channels.app")}
        body={t("support.help.channels.appBody")}
        note={t("support.help.channels.appNote")}
        action={<ReportButton />}
      />
    ) : null,
    whatsapp: whatsapp ? (
      <Channel
        key="whatsapp"
        icon={<MessageCircle aria-hidden className={cn(icon, "text-positive")} />}
        tone="bg-positive-soft"
        title={t("support.help.contact.whatsapp")}
        body={t("support.help.channels.whatsappBody")}
        note={
          hours ? (
            <span data-testid="help-hours">{t("support.help.contact.hours", { hours })}</span>
          ) : (
            t("support.help.channels.whatsappNote")
          )
        }
        action={
          <WhatsappLink
            digits={whatsapp}
            text={t("support.help.contact.whatsappText")}
            className={linkClass}
            testId="help-whatsapp"
          >
            <MessageCircle aria-hidden className="h-4 w-4" />
            {t("support.help.channels.whatsappOpen")}
          </WhatsappLink>
        }
      />
    ) : null,
    email: email ? (
      <Channel
        key="email"
        icon={<Mail aria-hidden className={cn(icon, "text-muted-foreground")} />}
        tone="bg-elevated"
        title={t("support.help.contact.email")}
        body={email}
        note={t("support.help.channels.emailNote")}
        action={
          <a href={`mailto:${email}`} className={linkClass} data-testid="help-email">
            <Mail aria-hidden className="h-4 w-4" />
            {t("support.help.channels.emailOpen")}
          </a>
        }
      />
    ) : null,
    telegram: telegram ? (
      <Channel
        key="telegram"
        icon={<Send aria-hidden className={cn(icon, "text-info")} />}
        tone="bg-info-soft"
        title={
          <>
            {t("support.help.contact.telegram")}
            <span className="rounded-full bg-elevated px-2 py-0.5 text-xs font-semibold text-muted-foreground">
              {t("support.help.contact.telegramNote")}
            </span>
          </>
        }
        body={t("support.help.channels.telegramBody")}
        note={t("support.help.channels.telegramNote")}
        action={
          <a
            href={telegram}
            target="_blank"
            rel="noopener noreferrer"
            className={linkClass}
            data-testid="help-telegram"
          >
            <Send aria-hidden className="h-4 w-4" />
            {t("support.help.channels.telegramOpen")}
          </a>
        }
      />
    ) : null,
  };
  const shown = order.map((channel) => channels[channel]).filter(Boolean);
  return (
    <section
      id="contact"
      aria-labelledby="help-contact"
      className="flex scroll-mt-[calc(var(--app-sticky-top,4rem)+1rem)] flex-col gap-3"
      data-testid="help-contact"
    >
      <div>
        <h2 id="help-contact" className="text-title">
          {t("support.help.channels.title")}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {canReport || whatsapp || email
            ? t("support.help.channels.subtitle")
            : t("support.help.contact.nothing")}
        </p>
        {!canReport && (whatsapp || email) ? (
          <p className="mt-1 text-caption text-muted-foreground">{t("support.help.contact.off")}</p>
        ) : null}
      </div>
      {shown.length > 0 ? <ul className="flex flex-col gap-2">{shown}</ul> : null}
      {shown.length > 0 ? (
        <div className="card-surface rounded-card p-4">
          <h3 className="text-sm font-semibold">{t("support.help.channels.quickTitle")}</h3>
          <ul className="mt-2 space-y-1.5 text-sm text-muted-foreground">
            <li>{t("support.help.channels.quick1")}</li>
            <li>{t("support.help.channels.quick2")}</li>
            <li>{t("support.help.channels.quick3")}</li>
          </ul>
        </div>
      ) : null}
      <p
        className="rounded-card border border-gold/40 bg-gold-soft px-4 py-3 text-sm leading-relaxed"
        data-testid="help-never"
      >
        <strong>{t("support.help.channels.neverStrong")}</strong> {t("support.help.channels.never")}
      </p>
    </section>
  );
}
