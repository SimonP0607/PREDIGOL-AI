/**
 * The profile in screens (plan maestro UX/UI 2026, decision 7; sheets U01-U07). The index lists the eight sections - a
 * row each, with its title and the one line it says (plan UX, B1) - and each row opens the section on its own screen
 * (/profile/privacy, /profile/security...), where its content mounts. The old addresses (/profile#privacy, the e-mails'
 * links, the guides') are sent to the section's screen.
 */
import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { t } from "@/lib/i18n";
import { Card } from "@/product/shared/States";
import type { BlockKey } from "./centre";

/** A row of the index: the way into a section, with the line it says. */
export function BlockRow({
  id,
  icon,
  title,
  summary,
}: {
  id: BlockKey;
  icon: ReactNode;
  title: string;
  /** The line it says (null while the summary loads or could not be read). */
  summary: string | null;
}) {
  return (
    <section id={id} className="scroll-mt-20" data-testid={`profile-block-${id}`} data-open="false">
      <Card as="div" className="overflow-hidden p-0">
        <h2 className="m-0" data-guide={`profile-${id}`}>
          <Link
            to="/profile/$section"
            params={{ section: id }}
            data-testid={`profile-toggle-${id}`}
            className="flex min-h-14 w-full items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-elevated/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          >
            <span aria-hidden className="mt-0.5 shrink-0 text-primary">
              {icon}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-title">{title}</span>
              {summary ? (
                <span
                  className="mt-0.5 block break-words text-xs font-normal text-muted-foreground"
                  data-testid={`profile-summary-${id}`}
                >
                  {summary}
                </span>
              ) : null}
            </span>
            <ChevronRight aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
          </Link>
        </h2>
      </Card>
    </section>
  );
}

/** A section on its own screen: the way back to the index, its title and its content. */
export function SectionScreen({
  id,
  icon,
  title,
  children,
}: {
  id: BlockKey;
  icon: ReactNode;
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="mx-auto max-w-3xl space-y-4" data-testid="profile-section" data-section={id}>
      <Link
        to="/profile"
        data-testid="profile-back"
        className="tap-y relative inline-flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground"
      >
        <ChevronLeft aria-hidden className="h-4 w-4" />
        {t("profile.title")}
      </Link>
      <section id={id} data-testid={`profile-block-${id}`} data-open="true">
        <h1 className="flex items-center gap-2.5 text-heading" data-guide={`profile-${id}`}>
          <span aria-hidden className="shrink-0 text-primary">
            {icon}
          </span>
          {title}
        </h1>
        <Card as="div" className="mt-3 px-5 pb-5 pt-4" data-testid={`profile-panel-${id}`}>
          {children}
        </Card>
      </section>
    </div>
  );
}
