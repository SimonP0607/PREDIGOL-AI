/**
 * When the notices are offered (plan UX, B7; section 34): «permiso en contexto, nunca al abrir: primero un aviso propio
 * con «Ahora no» y después el del navegador, al tocar la campana de un partido, seguir un equipo o guardar un pick».
 *
 * A page says a moment happened (`usePushMoment`): a team followed, a pick saved. The provider offers the card once, if
 * the owner made notices available (FBI_PUSH and the key, P12), this browser could receive them and does not yet, the
 * reader did not say «Ahora no» on this device in the last 30 days, nothing else asked them anything in this visit and the
 * guide is not up - and never to the owner. Opening PrediGol never brings it; the bell of a match asks in its own
 * sheet.
 */
import { useCallback, useMemo, useRef, useState, type ReactNode } from "react";
import { markOffered, wasOffered } from "@/lib/feedback/session";
import { useFeedbackReader } from "@/product/feedback/moments";
import { useGuides } from "@/product/guides/context";
import { PushOffer } from "./PushOffer";
import { markLater, mayOfferPush, PushOfferContext, saidLater, type PushMoment } from "./moments";
import { usePush } from "./usePush";

export function PushProvider({ children }: { children: ReactNode }) {
  const reader = useFeedbackReader();
  const guides = useGuides();
  const push = usePush(reader);
  const [offer, setOffer] = useState<PushMoment | null>(null);
  // what a moment reads: the values of now, not of the render that made the callback
  const now = useRef({ reader, tour: Boolean(guides.active), push });
  now.current = { reader, tour: Boolean(guides.active), push };

  const moment = useCallback((m: PushMoment) => {
    const { reader: isReader, tour: tourUp, push: p } = now.current;
    const facts = {
      reader: isReader,
      available: p.available,
      device: p.device?.status ?? null,
      hasDevices: (p.state?.devices.length ?? 0) > 0,
      later: saidLater(),
      asked: wasOffered(),
      tour: tourUp,
    };
    if (!mayOfferPush(facts)) return;
    markOffered(); // one question a visit: the survey of B6 waits for another
    setOffer(m);
  }, []);

  const value = useMemo(() => ({ moment }), [moment]);
  const state = push.state;
  return (
    <PushOfferContext.Provider value={value}>
      {children}
      {offer && state ? (
        <PushOffer
          moment={offer}
          rules={state}
          needsInstall={push.device?.status === "needs_install"}
          enable={push.enable}
          onLater={() => {
            markLater();
            setOffer(null);
          }}
          onDone={() => setOffer(null)}
        />
      ) : null}
    </PushOfferContext.Provider>
  );
}
