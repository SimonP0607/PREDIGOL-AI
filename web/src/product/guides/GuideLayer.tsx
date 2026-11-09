/**
 * The guide on the screen (plan UX-051; sections 8 and 9): the element ringed and the rest barely dimmed, and a card with the
 * step. Every card is a modal dialog (title and text linked; focus on the title; Tab goes round its buttons; Escape leaves);
 * touching outside does not close it. Below 1024 px the card is docked above the tab bar and the parlay button; from 1024 px
 * it sits beside the element. It follows the page when it scrolls, rotates or zooms, and brings the element into view first.
 * No timers and no animation: with "reduce motion" the page does not even scroll smoothly.
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { Link } from "@tanstack/react-router";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { HOW_PATH, cardAnchor } from "@/product/help/howItWorks";
import { findAnchor, placeCard, type Box } from "./anchors";
import { useGuides } from "./context";
import { cardsOf, numbered } from "./navigation";
import { ProfileBody, ProfileTitle } from "./ProfileBody";
import { GUIDES } from "./registry";

const BUTTON =
  "inline-flex min-h-11 items-center justify-center rounded-md px-4 py-2 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring";
const PRIMARY = cn(BUTTON, "bg-primary text-primary-foreground");
const QUIET = cn(BUTTON, "border border-border bg-card text-foreground hover:bg-elevated");
const TEXT = cn(BUTTON, "px-3 text-muted-foreground hover:text-foreground");

function box(el: HTMLElement): Box {
  const r = el.getBoundingClientRect();
  return { top: r.top, left: r.left, width: r.width, height: r.height };
}

/** Below 1024 px: how far above the foot of the screen the card sits - 8 px over the highest fixed bar or parlay button. */
function dockBottom(): number | null {
  const tops = Array.from(document.querySelectorAll<HTMLElement>('nav, [data-testid="slip-open"]'))
    .filter((e) => getComputedStyle(e).position === "fixed")
    .map((e) => e.getBoundingClientRect())
    .filter((r) => r.width > 0 && r.height > 0 && r.top >= window.innerHeight / 2)
    .map((r) => r.top);
  return tops.length > 0 ? Math.round(window.innerHeight - Math.min(...tops) + 8) : null;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

export function GuideLayer() {
  const guides = useGuides();
  const active = guides.active;
  const desk = useMediaQuery("(min-width: 1024px)");
  const title = useRef<HTMLHeadingElement>(null);
  const card = useRef<HTMLDivElement>(null);
  const [target, setTarget] = useState<Box | null>(null);
  const [place, setPlace] = useState<{ top: number; left: number } | null>(null);
  // Below 1024 px: the room the page gets at its foot, so an element near the end can still go up above the card (UX-074)
  const [room, setRoom] = useState(0);
  // ...and where the card is docked: 8 px above the tab bar or the parlay button, whichever is higher (null: the CSS's own)
  const [dock, setDock] = useState<number | null>(null);

  const def = active ? GUIDES[active.key] : null;
  const step = def && active ? cardsOf(def)[active.index] : undefined;
  const anchors = step?.anchors;

  const measure = useCallback(() => {
    const el = anchors && anchors.length > 0 ? findAnchor(anchors) : null;
    const found = el ? box(el) : null;
    setTarget(found);
    if (!desk) setDock(dockBottom());
    if (!desk && card.current) {
      setRoom(
        Math.max(0, Math.round(window.innerHeight - card.current.getBoundingClientRect().top)),
      );
    }
    if (desk && card.current) {
      const c = card.current.getBoundingClientRect();
      setPlace(
        placeCard(
          found,
          { width: c.width, height: c.height },
          { width: window.innerWidth, height: window.innerHeight },
        ),
      );
    } else {
      setPlace(null);
    }
  }, [anchors, desk]);

  // Bring the element into view (the bars are fixed and need nothing), then follow it while the page moves.
  useLayoutEffect(() => {
    const el = anchors && anchors.length > 0 ? findAnchor(anchors) : null;
    const bring = () => {
      if (!el || el.closest("nav, header")) return;
      const behavior = prefersReducedMotion() ? "auto" : "smooth";
      // the header may be hidden (a phone held sideways): only what is on the screen counts
      const head = Math.max(
        0,
        document.querySelector("header")?.getBoundingClientRect().bottom ?? 0,
      );
      const c = card.current?.getBoundingClientRect();
      const r = el.getBoundingClientRect();
      if (desk) {
        if (!c) {
          el.scrollIntoView({ block: "center", behavior });
          return;
        }
        // the card goes below the element or above it: both together are centred when they fit on the screen, else the
        // element is shown from its top and the card lies over its lower part
        const need = r.height + 12 + c.height;
        const avail = window.innerHeight - head - 24;
        const want = need <= avail ? head + 8 + (avail - need) / 2 : head + 8;
        window.scrollBy({ top: r.top - want, behavior });
        return;
      }
      // Below 1024 px the card is docked at the bottom: the element goes into the free band between the header and the
      // card (centred when it fits, from the top of the band when it does not), so the card never hides it (UX-074).
      const bottom = dockBottom();
      const cardTop = !c
        ? window.innerHeight * 0.6
        : bottom !== null
          ? window.innerHeight - bottom - c.height
          : c.top;
      const top = head + 8;
      const free = cardTop - 8 - top;
      const want = r.height <= free ? top + (free - r.height) / 2 : top;
      window.scrollBy({ top: r.top - want, behavior });
    };
    // the card mounts a frame after the layer: the first time its height is not known yet
    let placing = 0;
    if (card.current) bring();
    else placing = requestAnimationFrame(bring);
    measure();
    let frame = 0;
    const again = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(measure);
    };
    window.addEventListener("resize", again);
    window.addEventListener("scroll", again, true);
    window.visualViewport?.addEventListener("resize", again);
    const observer = el && typeof ResizeObserver !== "undefined" ? new ResizeObserver(again) : null;
    if (el) observer?.observe(el);
    return () => {
      cancelAnimationFrame(placing);
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", again);
      window.removeEventListener("scroll", again, true);
      window.visualViewport?.removeEventListener("resize", again);
      observer?.disconnect();
    };
  }, [anchors, measure, desk, active?.index, active?.mode]);

  if (!active || !def || !step) return null;

  const shown = numbered(def, findAnchor);
  const position = shown.indexOf(active.index) + 1;
  const welcome = step.id === "welcome";
  const resuming = active.mode === "resume";
  const lastShown = shown[shown.length - 1] ?? active.index;
  const last = !welcome && active.index === lastShown;
  const first = shown[0] === active.index;
  const base = `guides.${def.key}.${step.id}`;
  const own = def.key === "profile" && !resuming; // the guide of Perfil builds its words from the account
  const heading = resuming ? (
    t("guides.resume.title")
  ) : own ? (
    <ProfileTitle step={step.id} />
  ) : (
    t(`${base}.title`)
  );

  const docked = desk && place ? { top: place.top, left: place.left } : undefined;

  const spaced = !desk && !resuming && anchors !== undefined && anchors.length > 0;

  return (
    <>
      {spaced
        ? createPortal(
            <div
              aria-hidden
              data-testid="guide-room"
              style={{ height: room > 0 ? room : Math.round(window.innerHeight * 0.7) }}
            />,
            document.body,
          )
        : null}
      {target && !resuming ? (
        <div
          aria-hidden
          data-testid="guide-ring"
          className="pointer-events-none fixed z-[60] rounded-lg ring-2 ring-gold shadow-[0_0_0_9999px_rgba(0,0,0,0.45)]"
          style={{
            top: target.top - 4,
            left: target.left - 4,
            width: target.width + 8,
            height: target.height + 8,
          }}
        />
      ) : (
        <div aria-hidden className="pointer-events-none fixed inset-0 z-[60] bg-black/45" />
      )}
      <Dialog.Root open modal>
        <Dialog.Portal>
          <Dialog.Content
            ref={card}
            data-guide-card=""
            data-testid="guide-card"
            data-guide-key={def.key}
            data-step={active.index}
            aria-describedby="guide-body"
            onOpenAutoFocus={(e) => {
              e.preventDefault();
              title.current?.focus({ preventScroll: true });
            }}
            onCloseAutoFocus={(e) => e.preventDefault()}
            onEscapeKeyDown={(e) => {
              e.preventDefault();
              guides.dismiss("escape");
            }}
            onInteractOutside={(e) => e.preventDefault()}
            style={docked ?? (dock !== null ? { bottom: dock } : undefined)}
            className={cn(
              "fixed z-[70] rounded-xl border border-gold/40 bg-card p-4 shadow-lg focus:outline-none short:p-3",
              "inset-x-3 mx-auto max-w-md bottom-[calc(8.5rem+env(safe-area-inset-bottom))] short:bottom-[calc(7rem+env(safe-area-inset-bottom))] short:max-h-[calc(100dvh-8rem)] short:overflow-y-auto",
              "lg:inset-x-auto lg:bottom-auto lg:mx-0 lg:w-[26rem] lg:max-w-[calc(100vw-1.5rem)]",
              !docked && "lg:left-1/2 lg:top-1/2 lg:-translate-x-1/2 lg:-translate-y-1/2",
            )}
          >
            <p className="text-caption font-medium uppercase tracking-[0.06em] text-muted-foreground">
              {resuming
                ? t("guides.region")
                : welcome
                  ? t("guides.region")
                  : t("guides.progress", { n: position, total: shown.length })}
            </p>
            <Dialog.Title
              ref={title}
              tabIndex={-1}
              className="mt-0.5 font-display text-base font-semibold focus:outline-none"
            >
              {heading}
            </Dialog.Title>
            <div
              id="guide-body"
              className="mt-1 space-y-1.5 text-sm leading-relaxed text-foreground/90 short:space-y-1 short:leading-snug"
            >
              {resuming ? (
                <p>
                  {t("guides.resume.body", {
                    n: Math.max(position, 1),
                    total: shown.length,
                    name: t(`guides.names.${def.key}`),
                  })}
                </p>
              ) : welcome ? (
                <>
                  <p>{t("onboarding.welcome.about.picks")}</p>
                  <p>{t(`${base}.body`)}</p>
                </>
              ) : own ? (
                <ProfileBody step={step.id} />
              ) : (
                <p>{t(`${base}.body`)}</p>
              )}
              {last && def.more && !resuming ? (
                <p>
                  <Link
                    to={HOW_PATH}
                    hash={cardAnchor(def.more)}
                    onClick={guides.finish}
                    data-testid="guide-more"
                    className="inline-flex min-h-11 items-center font-medium text-primary underline-offset-4 hover:underline"
                  >
                    {t("guides.more")}
                  </Link>
                </p>
              ) : null}
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-x-3 gap-y-2 short:mt-1.5">
              {resuming ? (
                <>
                  <button
                    type="button"
                    onClick={guides.declineResume}
                    data-testid="guide-resume-no"
                    className={TEXT}
                  >
                    {t("guides.resume.no")}
                  </button>
                  <button
                    type="button"
                    onClick={guides.resume}
                    data-testid="guide-resume"
                    className={PRIMARY}
                  >
                    {t("guides.resume.yes")}
                  </button>
                </>
              ) : (
                <>
                  {def.mandatory || last ? (
                    <span />
                  ) : (
                    <button
                      type="button"
                      onClick={() => guides.skip("button")}
                      data-testid="guide-skip"
                      className={TEXT}
                    >
                      {t("guides.skip")}
                    </button>
                  )}
                  <div className="flex items-center gap-2">
                    {!welcome && !first ? (
                      <button
                        type="button"
                        onClick={guides.back}
                        data-testid="guide-back"
                        className={QUIET}
                      >
                        {t("guides.back")}
                      </button>
                    ) : null}
                    {welcome ? (
                      <button
                        type="button"
                        onClick={guides.next}
                        data-testid="guide-start"
                        className={PRIMARY}
                      >
                        {t(`${base}.start`)}
                      </button>
                    ) : last ? (
                      <button
                        type="button"
                        onClick={guides.finish}
                        data-testid="guide-finish"
                        className={PRIMARY}
                      >
                        {t("guides.finish")}
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={guides.next}
                        data-testid="guide-next"
                        className={PRIMARY}
                      >
                        {t("guides.next")}
                      </button>
                    )}
                  </div>
                </>
              )}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
