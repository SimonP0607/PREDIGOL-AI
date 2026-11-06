/**
 * /help/how-it-works (plan de cierre UX, 1.6): «Cómo funciona PrediGol». Eleven cards, each with what the part is, how it is
 * read, an example and a link to see it in the app. It is the one place the welcome, the tour, the help and the empty states
 * lead to; the definitions of the markets and of the states of a pick are the glossary's own (shown under their card), so
 * that a word never has two meanings. The examples use invented numbers, and the page says so.
 */
import { Link } from "@tanstack/react-router";
import { ArrowRight, BookOpen } from "lucide-react";
import { t } from "@/lib/i18n";
import { GLOSSARY_PATH, termAnchor, termName, termShort, type TermKey } from "@/lib/glossary";
import { PageTitle } from "@/product/shared/States";
import { ExplainLayers } from "@/product/shared/ExplainLayers";
import { HOW_CARDS, cardAnchor, type HowCard } from "./howItWorks";

const LINK =
  "tap-y relative inline-flex min-h-11 items-center gap-1.5 rounded-md text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

function Part({ label, children }: { label: string; children: string }) {
  return (
    <div>
      <dt className="text-caption font-medium uppercase tracking-[0.06em] text-subtle-foreground">
        {label}
      </dt>
      <dd className="mt-0.5 text-sm leading-relaxed">{children}</dd>
    </div>
  );
}

function Shown({ terms }: { terms: readonly TermKey[] }) {
  return (
    <div>
      <p className="text-caption font-medium uppercase tracking-[0.06em] text-subtle-foreground">
        {t("support.howItWorks.terms")}
      </p>
      <ul className="mt-1.5 space-y-2" data-testid="how-terms">
        {terms.map((term) => (
          <li key={term} className="text-sm leading-relaxed" data-term={term}>
            <Link
              to={GLOSSARY_PATH}
              hash={termAnchor(term)}
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              {termName(term)}
            </Link>
            <span className="text-muted-foreground">{`: ${termShort(term)}`}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Card({ card }: { card: HowCard }) {
  const key = `support.howItWorks.cards.${card.id}`;
  return (
    <article
      id={cardAnchor(card.id)}
      data-testid="how-card"
      data-card={card.id}
      aria-labelledby={`${cardAnchor(card.id)}-title`}
      className="scroll-mt-[calc(var(--app-sticky-top,4rem)+1rem)] rounded-xl border border-border bg-card p-4 target:border-primary target:ring-1 target:ring-primary/40"
    >
      <h2
        id={`${cardAnchor(card.id)}-title`}
        className="font-display text-lg font-semibold tracking-tight"
      >
        {t(`${key}.title`)}
      </h2>
      <dl className="mt-2.5 flex flex-col gap-3">
        <Part label={t("support.howItWorks.what")}>{t(`${key}.what`)}</Part>
        <Part label={t("support.howItWorks.read")}>{t(`${key}.read`)}</Part>
        <Part label={t("support.howItWorks.example")}>{t(`${key}.example`)}</Part>
      </dl>
      {card.shows ? (
        <div className="mt-3 border-t border-border pt-3">
          <Shown terms={card.shows} />
        </div>
      ) : null}
      <p className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1">
        <Link
          to={card.to as never}
          {...(card.hash ? { hash: card.hash } : {})}
          className={LINK}
          data-testid="how-go"
        >
          {t("support.howItWorks.go")}
          <ArrowRight aria-hidden className="h-4 w-4" />
        </Link>
        <Link to={GLOSSARY_PATH} hash={termAnchor(card.term)} className={LINK}>
          <BookOpen aria-hidden className="h-4 w-4" />
          {t("support.howItWorks.glossary")}
        </Link>
      </p>
    </article>
  );
}

export function HowItWorksPage() {
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5" data-testid="how-page">
      <PageTitle
        title={t("support.howItWorks.title")}
        subtitle={t("support.howItWorks.subtitle")}
      />
      <p className="text-sm leading-relaxed text-muted-foreground">
        {t("support.howItWorks.intro")}
      </p>
      <ExplainLayers />
      <nav aria-label={t("support.howItWorks.jump")} data-testid="how-index">
        <ul className="flex flex-wrap gap-2">
          {HOW_CARDS.map((card) => (
            <li key={card.id}>
              <a
                href={`#${cardAnchor(card.id)}`}
                className="tap-y relative inline-flex min-h-11 items-center rounded-full border border-border-strong px-3 text-sm font-medium hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {t(`support.howItWorks.cards.${card.id}.title`)}
              </a>
            </li>
          ))}
        </ul>
      </nav>
      <p className="text-caption text-subtle-foreground">{t("support.howItWorks.exampleNote")}</p>
      <div className="flex flex-col gap-4">
        {HOW_CARDS.map((card) => (
          <Card key={card.id} card={card} />
        ))}
      </div>
      <div className="rounded-xl border border-border bg-card p-4" data-testid="how-footer">
        <p className="text-sm text-muted-foreground">{t("support.howItWorks.footer")}</p>
        <p className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1">
          <Link to={GLOSSARY_PATH} className={LINK}>
            {t("support.howItWorks.footerGlossary")}
          </Link>
          <Link to="/help" className={LINK}>
            {t("support.howItWorks.footerHelp")}
          </Link>
        </p>
      </div>
    </div>
  );
}
