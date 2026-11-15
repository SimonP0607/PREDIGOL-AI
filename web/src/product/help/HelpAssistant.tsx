/**
 * The assistant of the help centre (plan maestro UX/UI 2026, decision 5; sheet H02): the reader writes what they want to
 * know and gets, at most, the three answers of the help that say it - each with where it comes from and the way to it.
 * Nothing is generated: `helpSearch.ts` searches the help's own texts in the browser. «Sigo igual» opens «Reportar un
 * problema» with what was typed, so nothing is written twice (WCAG 3.3.7). Shown only while FBI_HELP_ASSISTANT is on.
 */
import { useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronRight, MessagesSquare, Search } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { fieldVariants } from "@/components/ui/field";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Card } from "@/product/shared/States";
import { useReportProblem } from "@/product/support/report";
import { ask, type AssistantResult } from "./helpSearch";
import type { FaqId } from "./faq";

export function Assistant({ faqShown }: { faqShown: readonly FaqId[] }) {
  const report = useReportProblem();
  const [text, setText] = useState("");
  const [asked, setAsked] = useState("");
  const [result, setResult] = useState<AssistantResult>({ kind: "empty" });

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = text.trim();
    setAsked(q);
    setResult(ask(q, faqShown));
  }

  const person = report.available ? (
    <button
      type="button"
      onClick={() => report.open({ text: asked })}
      data-testid="assistant-person"
      className={buttonVariants({ variant: "secondary", size: "sm" })}
    >
      <MessagesSquare aria-hidden />
      {t("support.assistant.person")}
    </button>
  ) : null;

  return (
    <Card className="p-4">
      <section aria-labelledby="help-assistant" className="space-y-3" data-testid="help-assistant">
        <div>
          <h2 id="help-assistant" className="text-title">
            {t("support.assistant.title")}
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">{t("support.assistant.intro")}</p>
        </div>
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
          <label className="min-w-0 flex-1">
            <span className="sr-only">{t("support.assistant.label")}</span>
            <input
              type="text"
              value={text}
              maxLength={200}
              onChange={(e) => setText(e.target.value)}
              placeholder={t("support.assistant.placeholder")}
              data-testid="assistant-input"
              className={fieldVariants()}
            />
          </label>
          <button
            type="submit"
            disabled={text.trim().length === 0}
            data-testid="assistant-ask"
            className={buttonVariants({ variant: "primary" })}
          >
            <Search aria-hidden />
            {t("support.assistant.ask")}
          </button>
        </form>
        <div
          aria-live="polite"
          className="space-y-3"
          data-testid="assistant-result"
          data-kind={result.kind}
        >
          {result.kind === "blocked" ? (
            <div className="rounded-control border border-warning/40 bg-warning-soft px-3.5 py-3 text-sm leading-relaxed">
              <p>{t("support.assistant.blocked")}</p>
              <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                <Link to="/picks" className="font-semibold text-primary hover:underline">
                  {t("support.assistant.toPicks")}
                </Link>
                <Link
                  to="/legal/$doc"
                  params={{ doc: "responsible-gaming" }}
                  className="font-semibold text-primary hover:underline"
                >
                  {t("support.assistant.toResponsible")}
                </Link>
              </p>
            </div>
          ) : null}
          {result.kind === "none" ? (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                {t("support.assistant.none", { q: asked })}
              </p>
              {person}
            </div>
          ) : null}
          {result.kind === "found" ? (
            <>
              <ul className="space-y-2">
                {result.answers.map((a) => (
                  <li
                    key={`${a.source}-${a.id}`}
                    className="rounded-control border border-border bg-background-deep/50 px-3.5 py-3"
                    data-testid="assistant-answer"
                    data-source={a.source}
                  >
                    <p className="text-overline text-muted-foreground">{a.origin}</p>
                    <p className="mt-1.5 text-sm font-semibold">{a.title}</p>
                    <p className="mt-1 text-sm leading-relaxed text-foreground-soft">{a.text}</p>
                    <Link
                      to={a.to as never}
                      hash={a.hash}
                      className={cn(
                        "tap-y relative mt-2 inline-flex items-center gap-1 text-[0.8125rem] font-semibold text-primary underline-offset-4 hover:underline",
                      )}
                    >
                      {t("support.assistant.open")}
                      <ChevronRight aria-hidden className="h-3.5 w-3.5" />
                    </Link>
                  </li>
                ))}
              </ul>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                <p className="text-[0.8125rem] text-muted-foreground">
                  {t("support.assistant.still")}
                </p>
                {person}
              </div>
            </>
          ) : null}
        </div>
        <p className="text-caption text-subtle-foreground">{t("support.assistant.note")}</p>
      </section>
    </Card>
  );
}
