/**
 * «Reportar un problema» (plan UX, A14; section 32): one sheet, reachable from Ayuda, from every error a page shows and
 * from a match («¿Ves un dato incorrecto?»). The reader picks what it is about from big options - a sheet from the bottom
 * on a phone, from the side on a desk -, writes up to 2,000 characters, sees what goes with it (the screen, the version,
 * the device, the last error's reference; never a password or another form's contents) and gets the ticket's number and
 * when it will be answered. A privacy question goes to «Privacidad y datos», with its legal deadline. Nothing here
 * changes a pick, a probability or anything PrediGol publishes: it only writes to the reader's own tickets.
 */
import { useCallback, useId, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { CheckCircle2, Loader2, ShieldCheck } from "lucide-react";
import { v1, LiveApiError } from "@/lib/api/v1/client";
import type { SupportCategory, SupportTicket } from "@/lib/api/v1/types_support";
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { formatDateTime } from "@/lib/time";
import { cn } from "@/lib/utils";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { errorMessage } from "@/product/shared/States";
import { buildContext } from "./context";
import {
  CATEGORIES,
  MAX_OPEN,
  MAX_TEXT,
  ReportContext,
  type ReportOptions,
  type ReportValue,
} from "./report";
import { fieldVariants } from "@/components/ui/field";

/** A finger, or a screen too narrow for a side panel: the sheet comes up from the bottom. */
const SHEET_QUERY = "(pointer: coarse), (max-width: 639px)";

function fromBottom(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.(SHEET_QUERY).matches;
}

export function ReportProblemProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const [options, setOptions] = useState<ReportOptions | null>(null);
  const [side, setSide] = useState<"bottom" | "right">("bottom");
  const user = auth.user;
  const available =
    auth.status === "signed-in" &&
    Boolean(user?.support) &&
    (user?.role !== "SUPER_ADMIN" || auth.previewAsUser);
  const open = useCallback((next: ReportOptions = {}) => {
    setSide(fromBottom() ? "bottom" : "right");
    setOptions(next);
  }, []);
  const value = useMemo<ReportValue>(() => ({ available, open }), [available, open]);
  return (
    <ReportContext.Provider value={value}>
      {children}
      {available ? (
        <Sheet open={options !== null} onOpenChange={(next) => (next ? null : setOptions(null))}>
          <SheetContent
            side={side}
            closeLabel={t("support.report.close")}
            data-testid="report-sheet"
            className={cn(
              "overflow-y-auto",
              side === "bottom"
                ? "max-h-[92dvh] px-4 pb-[calc(1.25rem+env(safe-area-inset-bottom))] pt-5"
                : "w-full px-5 py-5 sm:max-w-md",
            )}
          >
            {options !== null ? (
              <ReportForm
                key={JSON.stringify(options)}
                options={options}
                onClose={() => setOptions(null)}
              />
            ) : null}
          </SheetContent>
        </Sheet>
      ) : null}
    </ReportContext.Provider>
  );
}

function ReportForm({ options, onClose }: { options: ReportOptions; onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [category, setCategory] = useState<SupportCategory | null>(options.category ?? null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<{ message: string; full: boolean } | null>(null);
  const [done, setDone] = useState<SupportTicket | null>(null);
  // the context as it is now (the screen behind the sheet), shown to the reader before it goes
  const [context] = useState(() =>
    buildContext({ matchId: options.matchId, requestId: options.requestId }),
  );
  const textId = useId();
  const countId = useId();
  const length = text.trim().length;

  async function send() {
    if (!category || length === 0 || busy) return;
    setBusy(true);
    setFailure(null);
    try {
      const ticket = await v1.openTicket({ category, text: text.trim(), context });
      setDone(ticket);
      await qc.invalidateQueries({ queryKey: ["me", "support"] });
    } catch (err) {
      const full = err instanceof LiveApiError && err.code === "too_many_open";
      setFailure({ message: errorMessage(err), full });
    } finally {
      setBusy(false);
    }
  }

  function go(to: string) {
    onClose();
    void navigate({ to: to as never });
  }

  if (done) {
    return (
      <div className="flex flex-col gap-3" data-testid="report-done" role="status">
        <SheetHeader className="pr-10 text-left">
          <SheetTitle className="flex items-center gap-2 font-display">
            <CheckCircle2 aria-hidden className="h-5 w-5 text-positive" />
            {t("support.report.done.title")}
          </SheetTitle>
          <SheetDescription className="text-sm text-foreground">
            {done.respond_by
              ? t("support.report.done.body", {
                  id: done.id,
                  date: formatDateTime(done.respond_by),
                })
              : t("support.ticket.title", { id: done.id })}
          </SheetDescription>
        </SheetHeader>
        <p className="text-sm text-muted-foreground">{t("support.report.done.email")}</p>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => go(`/help/messages/${done.id}`)}
            data-testid="report-see"
            className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground"
          >
            {t("support.report.done.see")}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-4 text-sm font-medium hover:bg-elevated"
          >
            {t("support.report.close")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      className="flex flex-col gap-4"
      data-testid="report-form"
      onSubmit={(e) => {
        e.preventDefault();
        void send();
      }}
    >
      <SheetHeader className="pr-10 text-left">
        <SheetTitle className="font-display">{t("support.report.title")}</SheetTitle>
        <SheetDescription>{t("support.report.description")}</SheetDescription>
      </SheetHeader>
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 text-sm font-semibold">{t("support.report.categoryLabel")}</legend>
        {CATEGORIES.map((c) => (
          <label
            key={c}
            data-testid={`report-category-${c}`}
            className={cn(
              "relative flex min-h-14 cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors",
              "focus-within:ring-2 focus-within:ring-ring",
              category === c
                ? "border-primary bg-primary/10"
                : "border-border bg-card hover:bg-elevated",
            )}
          >
            {/* the radio itself spans the whole option, invisible: the option is what a finger aims at (44 px and more) */}
            <input
              type="radio"
              name="report-category"
              value={c}
              checked={category === c}
              onChange={() => setCategory(c)}
              className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
            />
            <span
              aria-hidden
              className={cn(
                "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                category === c ? "border-primary" : "border-border-strong",
              )}
            >
              {category === c ? <span className="h-2 w-2 rounded-full bg-primary" /> : null}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium">
                {t(`support.report.category.${c}.label`)}
              </span>
              <span className="block text-caption text-muted-foreground">
                {t(`support.report.category.${c}.hint`)}
              </span>
            </span>
          </label>
        ))}
        <button
          type="button"
          onClick={() => go("/profile#privacy")}
          data-testid="report-privacy"
          className="flex min-h-14 items-start gap-3 rounded-lg border border-dashed border-border px-3 py-2.5 text-left hover:bg-elevated"
        >
          <ShieldCheck aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
          <span className="min-w-0">
            <span className="block text-sm font-medium">{t("support.report.privacy.label")}</span>
            <span className="block text-caption text-muted-foreground">
              {t("support.report.privacy.hint")} · {t("support.report.privacy.go")}
            </span>
          </span>
        </button>
      </fieldset>
      <div className="flex flex-col gap-1.5">
        <label htmlFor={textId} className="text-sm font-semibold">
          {t("support.report.textLabel")}
        </label>
        <textarea
          id={textId}
          value={text}
          rows={5}
          maxLength={MAX_TEXT}
          aria-describedby={countId}
          placeholder={t("support.report.textPlaceholder")}
          onChange={(e) => setText(e.target.value)}
          data-testid="report-text"
          className={fieldVariants({ size: "area" })}
        />
        <p id={countId} className="text-right text-caption text-subtle-foreground numeric">
          {t("support.report.counter", { count: text.length, max: MAX_TEXT })}
        </p>
        {context.match_id ? (
          <p className="text-caption text-muted-foreground">{t("support.report.matchLinked")}</p>
        ) : null}
      </div>
      <div
        className="rounded-md border border-border bg-muted/40 p-3 text-caption text-muted-foreground"
        data-testid="report-context"
      >
        <p className="font-semibold text-foreground">{t("support.report.context.title")}</p>
        <p className="mt-0.5">
          {t("support.report.context.body", { route: context.route ?? "—" })}
        </p>
        {context.request_id ? (
          <p className="mt-0.5 numeric">
            {t("support.report.context.error", { id: context.request_id })}
          </p>
        ) : null}
        <p className="mt-0.5">{t("support.report.context.never")}</p>
      </div>
      {failure ? (
        <div role="alert" className="text-sm text-negative" data-testid="report-error">
          <p>{failure.full ? t("support.report.full", { max: MAX_OPEN }) : failure.message}</p>
          {failure.full ? (
            <button
              type="button"
              onClick={() => go("/help")}
              className="mt-1 inline-flex min-h-11 items-center font-medium text-primary underline-offset-4 hover:underline"
            >
              {t("support.report.openTickets")}
            </button>
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-wrap justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="inline-flex min-h-11 items-center rounded-md border border-border-strong px-4 text-sm font-medium hover:bg-elevated"
        >
          {t("support.report.cancel")}
        </button>
        <button
          type="submit"
          disabled={!category || length === 0 || busy}
          data-testid="report-send"
          className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-4 text-sm font-semibold text-primary-foreground disabled:opacity-50"
        >
          {busy ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
          {busy ? t("support.report.sending") : t("support.report.send")}
        </button>
      </div>
    </form>
  );
}
