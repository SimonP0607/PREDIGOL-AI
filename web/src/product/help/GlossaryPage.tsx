/**
 * /help/glossary (plan UX, A3): every word PrediGol uses, with its one definition, in the reader's language - the
 * three questions first (forecast ≠ value ≠ pick), then the terms by group, each with its example and the terms
 * worth reading next. Every <GlossaryTerm> on any screen links here, to the term's own anchor; a search narrows the
 * list as the reader types (without accents or case: «linea» finds «Línea»).
 */
import { useMemo, useState } from "react";
import { Link } from "@tanstack/react-router";
import { Search } from "lucide-react";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import {
  CATEGORIES,
  GLOSSARY_PATH,
  TERM_KEYS,
  relatedTerms,
  termAnchor,
  termCategory,
  termLong,
  termMatches,
  termName,
  termShort,
  type TermKey,
} from "@/lib/glossary";
import { PageTitle } from "@/product/shared/States";
import { ExplainLayers } from "@/product/shared/ExplainLayers";
import { TourStart } from "@/product/tour/Tour";

export function GlossaryPage() {
  const [query, setQuery] = useState("");
  const shown = useMemo(() => TERM_KEYS.filter((k) => termMatches(k, query)), [query]);
  const groups = CATEGORIES.map(
    (c) => [c, shown.filter((k) => termCategory(k) === c)] as const,
  ).filter(([, keys]) => keys.length > 0);
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="glossary-page">
      <PageTitle title={t("glossary.page.title")} subtitle={t("glossary.page.subtitle")} />
      {/* Plan UX, A13: the optional four-step tour starts from the help (this page until /help arrives, A14). */}
      <TourStart />
      <ExplainLayers />
      <div className="sticky top-sticky z-10 -mx-1 bg-background/95 px-1 py-2 backdrop-blur">
        <label className="relative block">
          <span className="sr-only">{t("glossary.page.searchLabel")}</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-subtle-foreground"
          />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={t("glossary.page.search")}
            data-testid="glossary-search"
            className="h-11 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-base outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm"
          />
        </label>
        <p className="mt-1.5 text-caption text-subtle-foreground" aria-live="polite">
          {shown.length === 0
            ? t("glossary.page.noResults", { query: query.trim() })
            : t("glossary.page.count", { count: shown.length })}
        </p>
      </div>
      {groups.map(([category, keys]) => (
        <section
          key={category}
          aria-labelledby={`glossary-${category}`}
          className="flex flex-col gap-3"
        >
          <h2
            id={`glossary-${category}`}
            className="font-display text-lg font-semibold tracking-tight"
          >
            {t(`glossary.page.categories.${category}`)}
          </h2>
          <div className="flex flex-col gap-3">
            {keys.map((key) => (
              <TermEntry key={key} term={key} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function TermEntry({ term }: { term: TermKey }) {
  const related = relatedTerms(term);
  return (
    <article
      id={termAnchor(term)}
      data-testid="glossary-entry"
      data-term={term}
      className={cn(
        "scroll-mt-[calc(var(--app-sticky-top,4rem)+5.5rem)] rounded-xl border border-border bg-card p-4",
        "target:border-primary target:ring-1 target:ring-primary/40",
      )}
    >
      <h3 className="font-display text-base font-semibold">{termName(term)}</h3>
      <p className="mt-1.5 text-sm font-medium leading-relaxed">{termShort(term)}</p>
      <p className="mt-1.5 text-sm leading-relaxed text-muted-foreground">{termLong(term)}</p>
      {related.length > 0 ? (
        <p className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-caption">
          {/* Each related term is a 24 x 24 px target at least (WCAG 2.2, 2.5.8): on a phone the row wraps and a
              12 px word sat 4 px from the one below (axe target-size in A3's e2e). */}
          <span className="text-subtle-foreground">{t("glossary.page.related")}</span>
          {related.map((r) => (
            <Link
              key={r}
              to={GLOSSARY_PATH}
              hash={termAnchor(r)}
              className="tap-y relative inline-flex min-h-6 min-w-6 items-center justify-center rounded-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              {termName(r)}
            </Link>
          ))}
        </p>
      ) : null}
    </article>
  );
}
