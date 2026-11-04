/**
 * When the monthly survey comes up (plan UX, B6; section 40): «una vez cada 30 días, tras un momento útil (abrir un
 * análisis o ver un resultado); nunca en el login ni tras un error; si se cierra, no vuelve ese mes».
 *
 * A page says a useful moment happened (`useUsefulMoment`): a match's analysis read, a result seen. A little later
 * (OFFER_AFTER_MS, the page on the screen) the provider asks the server whether the survey is owed - on, and no answer
 * or close in the last 30 days - and offers it once in this visit, unless something failed in it (session.ts), the
 * optional tour's card is up, or the account is the owner's. Ignored, it leaves on the next page and may come back
 * another visit; answered or closed, the server keeps it away for 30 days. Nothing is asked before a useful moment, so
 * signing in never brings it.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRouterState } from "@tanstack/react-router";
import { live } from "@/lib/api/v1/queries";
import type { FeedbackTrigger } from "@/lib/api/v1/types_feedback";
import {
  OFFER_AFTER_MS,
  hadTrouble,
  markOffered,
  mayOffer,
  wasOffered,
} from "@/lib/feedback/session";
import { useTour } from "@/product/tour/steps";
import { CsatPrompt } from "./CsatPrompt";
import { FeedbackContext, useFeedbackReader, type FeedbackValue } from "./moments";

interface Offer {
  trigger: FeedbackTrigger;
  route: string;
  /** The page it came up on: left untouched, it goes with the next page. */
  shownOn: string;
}

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const reader = useFeedbackReader();
  const tour = useTour();
  const qc = useQueryClient();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [offer, setOffer] = useState<Offer | null>(null);
  const [touched, setTouched] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // what the timer reads when it fires: the values of that moment, not of the render that scheduled it
  const now = useRef({ reader, tour: Boolean(tour.step), pathname });
  now.current = { reader, tour: Boolean(tour.step), pathname };

  const present = useCallback(
    async (trigger: FeedbackTrigger, route: string): Promise<void> => {
      timer.current = null;
      if (!now.current.reader || now.current.tour || wasOffered() || hadTrouble()) return;
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        // a tab in the background: when the reader comes back to it
        const back = () => {
          if (document.visibilityState !== "visible") return;
          document.removeEventListener("visibilitychange", back);
          void present(trigger, route);
        };
        document.addEventListener("visibilitychange", back);
        return;
      }
      let state;
      try {
        state = await qc.fetchQuery({ ...live.survey, staleTime: 0 });
      } catch {
        return; // not reachable, consents owed: no survey, and the error is not the reader's to see
      }
      const facts = {
        reader: now.current.reader,
        enabled: state.enabled,
        due: state.due,
        trouble: hadTrouble(),
        offered: wasOffered(),
        tour: now.current.tour,
        visible: true,
      };
      if (!mayOffer(facts)) return;
      markOffered();
      setTouched(false);
      setOffer({ trigger, route, shownOn: now.current.pathname });
    },
    [qc],
  );

  const moment = useCallback(
    (trigger: FeedbackTrigger) => {
      if (!now.current.reader || timer.current !== null || wasOffered() || hadTrouble()) return;
      const route = now.current.pathname;
      timer.current = setTimeout(() => void present(trigger, route), OFFER_AFTER_MS);
    },
    [present],
  );

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  // left untouched, the card goes with the page it came up on (it was offered: not again in this visit)
  useEffect(() => {
    if (offer && !touched && pathname !== offer.shownOn) setOffer(null);
  }, [pathname, offer, touched]);

  const value = useMemo<FeedbackValue>(() => ({ moment }), [moment]);
  return (
    <FeedbackContext.Provider value={value}>
      {children}
      {offer && reader ? (
        <CsatPrompt
          trigger={offer.trigger}
          route={offer.route}
          onEngage={() => setTouched(true)}
          onDone={() => setOffer(null)}
        />
      ) : null}
    </FeedbackContext.Provider>
  );
}
