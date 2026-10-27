/**
 * PrediGol's own question before the browser's (plan UX, B7; section 34: «primero un aviso propio con «Ahora no» y
 * después el del navegador»): one card at the foot of the page, in the tour's and the survey's place - above the tab bar
 * and the parlay button on a phone, bottom left at a desk. It says what would arrive and its limits; «Activar avisos»
 * asks the browser (from that tap), «Ahora no» or the cross keeps the offer away from this device for 30 days.
 *
 * On an iPhone in Safari there is nothing to turn on yet: the card shows how to install PrediGol (notices reach the
 * installed app only). Not modal, it does not take the focus when it appears; Escape closes it as «Ahora no».
 *
 * PushOfferView draws it from what it is given (a test renders it without a session); PushOffer acts.
 */
import { useEffect, useId, useState } from "react";
import { BellRing, Loader2, X } from "lucide-react";
import type { PushState } from "@/lib/api/v1/types_push";
import { t } from "@/lib/i18n";
import type { EnableResult } from "@/lib/push";
import { InstallGuide } from "./InstallGuide";
import type { PushMoment } from "./moments";

export type OfferPhase = "ask" | "install" | "busy" | "done" | "denied" | "failed";

/** The tour's and the survey's place: never over the tab bar or the parlay button (CsatPrompt.tsx draws the same). */
const FRAME =
  "fixed inset-x-3 bottom-[calc(8.5rem+env(safe-area-inset-bottom))] z-40 mx-auto max-h-[calc(100dvh-10rem)] max-w-md overflow-y-auto rounded-xl border border-gold/40 bg-card p-4 shadow-lg short:bottom-[calc(7rem+env(safe-area-inset-bottom))] lg:bottom-6 lg:left-6 lg:right-auto lg:mx-0 lg:w-[26rem]";

const PRIMARY =
  "inline-flex min-h-11 flex-[2] items-center justify-center gap-2 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60";
const SECONDARY =
  "inline-flex min-h-11 flex-1 items-center justify-center rounded-lg border border-border-strong px-4 text-sm font-medium transition-colors hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";

export function PushOfferView({
  moment,
  phase,
  rules,
  onEnable,
  onLater,
  onClose,
}: {
  moment: PushMoment;
  phase: OfferPhase;
  /** The quiet hours and the daily ceiling, from GET /me/push. */
  rules: Pick<PushState, "quiet_start" | "quiet_end" | "daily_cap">;
  onEnable: () => void;
  /** «Ahora no», the cross or Escape before an answer. */
  onLater: () => void;
  /** After an answer. */
  onClose: () => void;
}) {
  const titleId = useId();
  const answered = phase === "done" || phase === "denied" || phase === "failed";
  const close = answered ? onClose : onLater;
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") close();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);

  const title =
    phase === "install"
      ? t("push.offer.installTitle")
      : moment.reason === "follow"
        ? t("push.offer.follow.title", { team: moment.team })
        : t("push.offer.save.title");
  return (
    <div
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      data-testid="push-offer"
      data-phase={phase}
      className={FRAME}
    >
      <div className="flex items-start gap-3">
        <BellRing aria-hidden className="mt-0.5 h-5 w-5 shrink-0 text-gold-strong" />
        <h2
          id={titleId}
          className="min-w-0 flex-1 font-display text-base font-semibold leading-snug"
        >
          {title}
        </h2>
        <button
          type="button"
          onClick={close}
          aria-label={answered ? t("push.offer.close") : t("push.offer.later")}
          data-testid="push-offer-close"
          className="tap relative -mr-1 -mt-1 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:bg-elevated hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-2 space-y-3 pl-8">
        {phase === "install" ? (
          <InstallGuide platform="ios" />
        ) : phase === "done" || phase === "denied" || phase === "failed" ? (
          <p role="status" className="text-sm" data-testid="push-offer-result">
            {t(`push.offer.${phase}`)}
          </p>
        ) : (
          <>
            <p className="text-sm">
              {moment.reason === "follow" ? t("push.offer.follow.body") : t("push.offer.save.body")}
            </p>
            <p className="text-caption text-muted-foreground">
              {t("push.offer.rules", {
                from: rules.quiet_start,
                to: rules.quiet_end,
                cap: rules.daily_cap,
              })}
            </p>
          </>
        )}
      </div>
      <div className="mt-4 flex gap-2">
        {phase === "ask" || phase === "busy" ? (
          <>
            <button
              type="button"
              onClick={onLater}
              disabled={phase === "busy"}
              data-testid="push-offer-later"
              className={SECONDARY}
            >
              {t("push.offer.later")}
            </button>
            <button
              type="button"
              onClick={onEnable}
              disabled={phase === "busy"}
              data-testid="push-offer-enable"
              className={PRIMARY}
            >
              {phase === "busy" ? <Loader2 aria-hidden className="h-4 w-4 animate-spin" /> : null}
              {phase === "busy" ? t("push.offer.busy") : t("push.offer.enable")}
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={phase === "install" ? onLater : onClose}
            data-testid="push-offer-ok"
            className={SECONDARY}
          >
            {phase === "install" ? t("push.offer.understood") : t("push.offer.close")}
          </button>
        )}
      </div>
    </div>
  );
}

export function PushOffer({
  moment,
  rules,
  needsInstall,
  enable,
  onLater,
  onDone,
}: {
  moment: PushMoment;
  rules: Pick<PushState, "quiet_start" | "quiet_end" | "daily_cap">;
  /** An iPhone in Safari: the install guide instead of the question. */
  needsInstall: boolean;
  enable: () => Promise<EnableResult>;
  onLater: () => void;
  onDone: () => void;
}) {
  const [phase, setPhase] = useState<OfferPhase>(needsInstall ? "install" : "ask");
  useEffect(() => {
    if (phase !== "done") return;
    const timer = setTimeout(onDone, 6_000);
    return () => clearTimeout(timer);
  }, [phase, onDone]);

  function turnOn() {
    setPhase("busy");
    // enable() asks the browser before anything else awaits: the tap's activation is still there
    void enable().then((result) => {
      if (result.ok) setPhase("done");
      else if (result.reason === "denied") setPhase("denied");
      else if (result.reason === "dismissed") onLater();
      else setPhase("failed");
    });
  }

  return (
    <PushOfferView
      moment={moment}
      phase={phase}
      rules={rules}
      onEnable={turnOn}
      onLater={onLater}
      onClose={onDone}
    />
  );
}
