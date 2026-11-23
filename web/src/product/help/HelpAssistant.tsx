/**
 * The assistant of the help centre (plan maestro UX/UI 2026, decision 5; sheet H02; UX-149): a conversation by steps. The
 * reader writes what they want to know and the assistant answers with, at most, the three answers of the help that say it -
 * each with where it comes from and the way to it - then asks whether that solved it. «Sigo igual» offers a person: the
 * message goes with what was already said, so nothing is written twice (WCAG 3.3.7), or WhatsApp when the owner gave it.
 *
 * Nothing is generated: `helpSearch.ts` searches the help's own texts in the browser; the conversation lives in this view
 * only (nothing is stored or sent until the reader sends it to a person). Shown only while FBI_HELP_ASSISTANT is on.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "@tanstack/react-router";
import {
  ChevronRight,
  MessageCircle,
  MessagesSquare,
  SendHorizontal,
  Sparkles,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { useReportProblem } from "@/product/support/report";
import { WhatsappLink } from "@/product/support/WhatsappLink";
import { ask, type AssistantAnswer } from "./helpSearch";
import type { FaqId } from "./faq";
import { NO_REACH, type Reach } from "./reach";

export type Turn =
  | { who: "me"; text: string }
  | { who: "bot"; kind: "found"; answers: AssistantAnswer[]; asked: string }
  | { who: "bot"; kind: "none" | "blocked"; asked: string }
  | { who: "bot"; kind: "solved" }
  | { who: "bot"; kind: "person" };

/** The next turns after the reader writes `text` (pure): what they said, and the help's answer to it. */
export function answerTo(
  text: string,
  faqShown: readonly FaqId[],
  reach: Reach = NO_REACH,
): Turn[] {
  const q = text.trim();
  if (!q) return [];
  const result = ask(q, faqShown, reach);
  const me: Turn = { who: "me", text: q };
  if (result.kind === "found")
    return [me, { who: "bot", kind: "found", answers: result.answers, asked: q }];
  if (result.kind === "blocked") return [me, { who: "bot", kind: "blocked", asked: q }];
  return [me, { who: "bot", kind: "none", asked: q }];
}

/** What the reader wrote in this conversation, for the message to a person. */
export function transcript(turns: readonly Turn[]): string {
  return turns
    .filter((x): x is Extract<Turn, { who: "me" }> => x.who === "me")
    .map((x) => x.text)
    .join("\n")
    .slice(0, 1000);
}

const BOT =
  "max-w-[92%] rounded-feature rounded-tl-md bg-elevated px-4 py-3 text-sm leading-relaxed";
const ME =
  "ml-auto max-w-[85%] rounded-feature rounded-tr-md bg-primary-soft px-4 py-3 text-sm leading-relaxed text-foreground";
const QUICK =
  "tap-y relative inline-flex min-h-9 items-center rounded-full border border-border bg-card px-3.5 text-[0.8125rem] font-semibold hover:bg-elevated focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary";

function AnswerCard({ a }: { a: AssistantAnswer }) {
  return (
    <li
      className="rounded-control border border-border bg-background-deep/50 px-3.5 py-3"
      data-testid="assistant-answer"
      data-source={a.source}
    >
      <p className="text-sm font-semibold">{a.title}</p>
      <p className="mt-1 text-sm leading-relaxed text-foreground-soft">{a.text}</p>
      <Link
        to={a.to as never}
        hash={a.hash}
        className="tap-y relative mt-2 flex items-center justify-between gap-2 border-t border-border pt-2 text-[0.8125rem] font-semibold text-primary underline-offset-4 hover:underline"
      >
        <span>
          {t("support.assistant.fromHelp")} {a.origin}
        </span>
        <ChevronRight aria-hidden className="h-3.5 w-3.5 shrink-0" />
      </Link>
    </li>
  );
}

export function Assistant({
  faqShown,
  whatsapp = null,
  reach = NO_REACH,
}: {
  faqShown: readonly FaqId[];
  /** The channels that are published: an answer names only these (AP-H01). */
  reach?: Reach;
  /** The owner's WhatsApp, only when it is published. */
  whatsapp?: string | null;
}) {
  const report = useReportProblem();
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (turns.length > 0) end.current?.scrollIntoView?.({ block: "nearest" });
  }, [turns.length]);

  function submit(e: FormEvent) {
    e.preventDefault();
    const next = answerTo(text, faqShown, reach);
    if (!next.length) return;
    setTurns((all) => [...all, ...next]);
    setText("");
  }

  const last = turns[turns.length - 1];
  const lastBot = last && last.who === "bot" ? last : null;
  const said = transcript(turns);

  const personOffer = (
    <div className="flex flex-col gap-2">
      {report.available ? (
        <button
          type="button"
          onClick={() => report.open({ text: said })}
          data-testid="assistant-person"
          className={buttonVariants({ variant: "primary" })}
        >
          <MessagesSquare aria-hidden />
          {t("support.assistant.sendPerson")}
        </button>
      ) : null}
      {whatsapp ? (
        <WhatsappLink
          digits={whatsapp}
          text={`${t("support.help.contact.whatsappText")} ${said}`.slice(0, 900)}
          className={buttonVariants({ variant: "secondary" })}
          testId="assistant-whatsapp"
        >
          <MessageCircle aria-hidden className="h-4 w-4" />
          {t("support.assistant.whatsapp")}
        </WhatsappLink>
      ) : null}
      {!report.available && !whatsapp ? (
        <p className="text-[0.8125rem] text-muted-foreground">
          {t("support.help.contact.nothing")}
        </p>
      ) : null}
    </div>
  );

  return (
    <section
      aria-labelledby="help-assistant"
      className="flex min-h-0 flex-1 flex-col"
      data-testid="help-assistant"
    >
      <h2 id="help-assistant" className="sr-only">
        {t("support.assistant.title")}
      </h2>
      <div
        className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain pb-3"
        role="log"
        aria-live="polite"
        aria-relevant="additions"
        data-testid="assistant-result"
        data-kind={lastBot ? lastBot.kind : "empty"}
      >
        <p className="rounded-feature border border-border bg-card px-4 py-3 text-[0.8125rem] leading-relaxed text-muted-foreground">
          {t("support.assistant.scope")}
        </p>
        {turns.map((turn, i) =>
          turn.who === "me" ? (
            <p key={i} className={ME} data-testid="assistant-me">
              {turn.text}
            </p>
          ) : (
            <div key={i} className={BOT} data-testid="assistant-bot" data-kind={turn.kind}>
              {turn.kind === "found" ? (
                <>
                  <p>{t("support.assistant.foundIntro", { count: turn.answers.length })}</p>
                  <ul className="mt-2 space-y-2">
                    {turn.answers.map((a) => (
                      <AnswerCard key={`${a.source}-${a.id}`} a={a} />
                    ))}
                  </ul>
                </>
              ) : turn.kind === "blocked" ? (
                <>
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
                </>
              ) : turn.kind === "none" ? (
                <>
                  <p>{t("support.assistant.none", { q: turn.asked })}</p>
                  {i === turns.length - 1 ? <div className="mt-3">{personOffer}</div> : null}
                </>
              ) : turn.kind === "solved" ? (
                <p>{t("support.assistant.solvedReply")}</p>
              ) : (
                <>
                  <p>{t("support.assistant.personReply")}</p>
                  <div className="mt-3">{personOffer}</div>
                  <p className="mt-2 text-caption text-muted-foreground">
                    {t("support.help.contact.urgent")}
                  </p>
                </>
              )}
            </div>
          ),
        )}
        {lastBot && lastBot.kind === "found" ? (
          <div className="flex flex-wrap gap-2" data-testid="assistant-quick">
            <button
              type="button"
              className={QUICK}
              onClick={() =>
                setTurns((all) => [
                  ...all,
                  { who: "me", text: t("support.assistant.solved") },
                  { who: "bot", kind: "solved" },
                ])
              }
            >
              {t("support.assistant.solved")}
            </button>
            <button
              type="button"
              className={QUICK}
              data-testid="assistant-still"
              onClick={() =>
                setTurns((all) => [
                  ...all,
                  { who: "me", text: t("support.assistant.stillSame") },
                  { who: "bot", kind: "person" },
                ])
              }
            >
              {t("support.assistant.stillSame")}
            </button>
          </div>
        ) : null}
        <div ref={end} />
      </div>
      <form onSubmit={submit} className="border-t border-border pt-3">
        <div className="flex items-center gap-2">
          <label className="min-w-0 flex-1">
            <span className="sr-only">{t("support.assistant.label")}</span>
            <input
              type="text"
              value={text}
              maxLength={200}
              onChange={(e) => setText(e.target.value)}
              placeholder={t("support.assistant.write")}
              data-testid="assistant-input"
              autoComplete="off"
              className="h-12 w-full rounded-full border border-border bg-background-deep/60 px-4 text-base outline-none placeholder:text-subtle-foreground focus-visible:border-primary sm:text-sm"
            />
          </label>
          <button
            type="submit"
            disabled={text.trim().length === 0}
            data-testid="assistant-ask"
            aria-label={t("support.assistant.ask")}
            className="motion-press inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:bg-elevated disabled:text-subtle-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          >
            <SendHorizontal aria-hidden className="h-5 w-5" />
          </button>
        </div>
        <p className="mt-2 text-center text-caption text-subtle-foreground">
          {t("support.assistant.privacy")}
        </p>
      </form>
    </section>
  );
}

/** The conversation in its own view (sheet H02): a sheet from the bottom on a phone, at the side on a desk. */
export function AssistantSheet({
  open,
  onOpenChange,
  faqShown,
  whatsapp,
  reach,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  faqShown: readonly FaqId[];
  whatsapp: string | null;
  reach: Reach;
}) {
  const desk = useMediaQuery("(min-width: 768px)");
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side={desk ? "right" : "bottom"}
        closeLabel={t("common.close")}
        data-testid="assistant-sheet"
        className={cn(
          "flex flex-col gap-3",
          desk
            ? "w-full px-5 py-5 sm:max-w-md"
            : "h-[92dvh] px-4 pb-[calc(1rem+env(safe-area-inset-bottom))] pt-5",
        )}
      >
        <div className="flex items-center gap-3 pr-10">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-field bg-primary-soft">
            <Sparkles aria-hidden className="h-5 w-5 text-primary" />
          </span>
          <div className="min-w-0">
            <SheetTitle className="text-subheading">{t("support.assistant.title")}</SheetTitle>
            <SheetDescription className="text-caption text-muted-foreground">
              {t("support.assistant.byline")}
            </SheetDescription>
          </div>
        </div>
        {open ? <Assistant faqShown={faqShown} whatsapp={whatsapp} reach={reach} /> : null}
      </SheetContent>
    </Sheet>
  );
}
