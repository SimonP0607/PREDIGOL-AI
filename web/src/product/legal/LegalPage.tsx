/**
 * A legal text as the reader accepts it (plan UX, A4): the terms, the processing policy, the responsible-gaming page.
 * The text comes from the API - the same source the consent's sha256 is computed from - with its version, its date,
 * its fingerprint and its history. A draft says so at the top. On a phone (320 px) the contents fold away and every
 * section keeps its anchor (/legal/privacy#derechos).
 */
import { useQuery } from "@tanstack/react-query";
import { FileText, History } from "lucide-react";
import { v1 } from "@/lib/api/v1/client";
import type { LegalDocumentName } from "@/lib/api/v1/types_customer";
import { t, useI18n } from "@/lib/i18n";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { Card, ErrorState, PageTitle } from "@/product/shared/States";
import { LEGAL_DOCUMENTS, dayOf, legalPath } from "./links";

export function LegalPage({ document }: { document: LegalDocumentName }) {
  const { locale } = useI18n();
  // The contents are open on a wide screen and folded on a phone, where the text itself needs the room.
  const wide = useMediaQuery("(min-width: 1024px)");
  const doc = useQuery({
    queryKey: ["legal", document, locale],
    queryFn: () => v1.legalDocument(document, locale),
    staleTime: 10 * 60_000,
  });
  if (doc.isPending) {
    return (
      <div className="mx-auto max-w-3xl space-y-3" aria-busy="true">
        <div className="h-8 w-2/3 animate-pulse rounded bg-elevated" />
        <div className="h-4 w-full animate-pulse rounded bg-elevated" />
        <div className="h-4 w-5/6 animate-pulse rounded bg-elevated" />
      </div>
    );
  }
  if (doc.isError) {
    return (
      <Card className="mx-auto max-w-3xl">
        <ErrorState error={doc.error} onRetry={() => void doc.refetch()} />
      </Card>
    );
  }
  const d = doc.data;
  return (
    <article
      className="mx-auto flex w-full max-w-3xl flex-col gap-5"
      data-testid="legal-page"
      data-document={d.document}
      data-version={d.version}
    >
      <PageTitle title={d.title} subtitle={d.summary} />
      {d.draft ? (
        <p
          role="note"
          className="rounded-md border border-warning/40 bg-warning-soft px-3 py-2 text-sm font-medium text-warning"
          data-testid="legal-draft"
        >
          {t("legal.page.draft")}
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground" data-testid="legal-version">
        {t("legal.page.version", { version: d.version, date: dayOf(d.date) })}
      </p>

      <details className="rounded-md border border-border bg-card" open={wide}>
        <summary className="flex min-h-11 cursor-pointer items-center gap-2 px-4 py-2 text-sm font-semibold">
          <FileText aria-hidden className="h-4 w-4 text-primary" />
          {t("legal.page.contents")}
        </summary>
        <ol className="space-y-1 px-4 pb-3 text-sm">
          {d.sections.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                className="inline-block py-1 text-muted-foreground underline-offset-2 hover:text-foreground hover:underline pointer-coarse:py-2.5"
              >
                {s.title}
              </a>
            </li>
          ))}
        </ol>
      </details>

      {d.sections.map((s) => (
        <section
          key={s.id}
          id={s.id}
          className="scroll-mt-20 space-y-2"
          aria-labelledby={`h-${s.id}`}
        >
          <h2 id={`h-${s.id}`} className="font-display text-base font-semibold">
            {s.title}
          </h2>
          {s.blocks.map((b, i) =>
            b.ul ? (
              <ul key={i} className="list-disc space-y-1 pl-5 text-sm leading-relaxed">
                {b.ul.map((item, j) => (
                  <li key={j} className="break-words">
                    {item}
                  </li>
                ))}
              </ul>
            ) : (
              <p key={i} className="break-words text-sm leading-relaxed">
                {b.p}
              </p>
            ),
          )}
        </section>
      ))}

      <details className="rounded-md border border-border bg-card">
        <summary className="flex min-h-11 cursor-pointer items-center gap-2 px-4 py-2 text-sm font-semibold">
          <History aria-hidden className="h-4 w-4 text-primary" />
          {t("legal.page.history")}
        </summary>
        <ul className="space-y-3 px-4 pb-4 text-sm" data-testid="legal-history">
          {d.history.map((v) => (
            <li key={v.version} className="space-y-0.5">
              <div className="font-medium">
                {t("legal.page.historyRow", { version: v.version, date: dayOf(v.date) })}
                {v.material ? (
                  <span className="text-muted-foreground">
                    {" "}
                    · {t("legal.page.historyMaterial")}
                  </span>
                ) : null}
                {v.draft ? (
                  <span className="text-muted-foreground"> · {t("legal.page.historyDraft")}</span>
                ) : null}
              </div>
              <p className="text-muted-foreground">{v.changes}</p>
            </li>
          ))}
        </ul>
      </details>

      <p
        className="break-all font-mono text-caption text-subtle-foreground"
        data-testid="legal-sha256"
      >
        {t("legal.page.fingerprint", { sha: d.sha256 })}
      </p>

      <nav aria-label={t("legal.page.others")} className="border-t border-border pt-4">
        <ul className="flex flex-wrap gap-2">
          {LEGAL_DOCUMENTS.filter((o) => o !== d.document).map((o) => (
            <li key={o}>
              <a
                href={legalPath(o)}
                className="tap-y relative inline-flex rounded-md border border-border-strong px-3 py-1.5 text-sm hover:bg-elevated"
              >
                {t(`legal.doc.${o}`)}
              </a>
            </li>
          ))}
        </ul>
      </nav>
    </article>
  );
}
