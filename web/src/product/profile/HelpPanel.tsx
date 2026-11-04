/**
 * The account centre's Ayuda (plan UX, B1; section 21): the help centre, «Reportar un problema» (the sheet of A14), the
 * reader's messages with what they wait for, the glossary and - once the owner gives it (P7) - WhatsApp. Novedades join
 * this block with B6.
 */
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, ChevronRight, LifeBuoy, MessageCircle, MessagesSquare } from "lucide-react";
import { live } from "@/lib/api/v1/queries";
import type { AccountSummary } from "@/lib/api/v1/types_account";
import { t } from "@/lib/i18n";
import { whatsappLink } from "@/product/membership/membership";
import { useReportProblem } from "@/product/support/report";
import { messagesHint } from "./centre";

const ROW =
  "flex min-h-12 w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Line({ icon, title, hint }: { icon: ReactNode; title: string; hint?: string | null }) {
  return (
    <>
      <span aria-hidden className="shrink-0 text-primary">
        {icon}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block font-medium">{title}</span>
        {hint ? <span className="block text-caption text-muted-foreground">{hint}</span> : null}
      </span>
      <ChevronRight aria-hidden className="h-4 w-4 shrink-0 text-muted-foreground" />
    </>
  );
}

export function HelpPanel({ summary }: { summary: AccountSummary | undefined }) {
  const report = useReportProblem();
  const contact = useQuery({ ...live.supportContact, enabled: Boolean(summary?.help.whatsapp) });
  const whatsapp = contact.data?.whatsapp ?? null;
  return (
    <nav aria-label={t("profile.centre.help.label")} data-testid="help-panel">
      <ul className="space-y-1">
        <li>
          <Link to="/help" className={ROW} data-testid="profile-help-center">
            <Line
              icon={<BookOpen className="h-5 w-5" />}
              title={t("profile.centre.help.center")}
              hint={t("profile.centre.help.centerHint")}
            />
          </Link>
        </li>
        {report.available ? (
          <li>
            <button
              type="button"
              onClick={() => report.open()}
              className={ROW}
              data-testid="profile-report"
            >
              <Line
                icon={<LifeBuoy className="h-5 w-5" />}
                title={t("support.help.contact.report")}
                hint={t("profile.centre.help.reportHint")}
              />
            </button>
          </li>
        ) : null}
        <li>
          <Link to="/help" hash="tickets" className={ROW} data-testid="profile-messages">
            <Line
              icon={<MessagesSquare className="h-5 w-5" />}
              title={t("profile.centre.help.messages")}
              hint={messagesHint(summary) ?? t("profile.centre.summary.helpNone")}
            />
          </Link>
        </li>
        <li>
          <Link to="/help/glossary" className={ROW} data-testid="profile-glossary">
            <Line
              icon={<BookOpen className="h-5 w-5" />}
              title={t("nav.glossary")}
              hint={t("nav.moreHint.glossary")}
            />
          </Link>
        </li>
        {whatsapp ? (
          <li>
            <a
              href={whatsappLink(whatsapp, t("support.help.contact.whatsappText"))}
              target="_blank"
              rel="noopener noreferrer"
              className={ROW}
              data-testid="profile-whatsapp"
            >
              <Line
                icon={<MessageCircle className="h-5 w-5" />}
                title={t("support.help.contact.whatsapp")}
                hint={t("profile.centre.help.whatsappHint")}
              />
            </a>
          </li>
        ) : null}
      </ul>
    </nav>
  );
}
