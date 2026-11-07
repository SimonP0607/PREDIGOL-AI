/**
 * The guides' engine (plan UX-051; PLAN_BIENVENIDA_RECORRIDO, sections 3, 7 and 11): one guide at a time, whatever launched it.
 *
 * Replaces the optional tour and the first-visit hints of A13. A screen says it has its data (`useGuideScreen`); the guide that
 * opens on it launches by itself once, unless something stands in its way (eligibility.ts: the rules against fatigue) or the
 * reader asked for it ("?", Ayuda). Everything the reader does is recorded: at once in the account the page holds, then in the
 * API (one write at a time per guide, in order) - a write that cannot be sent waits in this device's queue (queue.ts) and goes
 * the next time. The survey and the offer of notices wait while a guide is up (`active`).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { v1 } from "@/lib/api/v1/client";
import type { Me } from "@/lib/api/v1/types_auth";
import type { Envelope } from "@/lib/api/v1/types";
import type { Today } from "@/lib/api/v1/types_today";
import type { GuideIn, GuideKey } from "@/lib/api/v1/types_guides";
import { useAuth } from "@/lib/auth/AuthProvider";
import { originOf, track } from "@/lib/track";
import { anotherLayerOpen, findAnchor } from "./anchors";
import { GuideLayer } from "./GuideLayer";
import {
  GuidesContext,
  type ActiveGuide,
  type GuidesValue,
  type LeaveMethod,
  type Trigger,
} from "./context";
import { blockedBy, owed, type Facts } from "./eligibility";
import { firstFrom, neighbour } from "./navigation";
import { dequeue, enqueue, flush } from "./queue";
import { GUIDES, GUIDE_LIST, launchable } from "./registry";
import { applied, seenOf, withGuide } from "./state";

const ME_KEY = ["auth", "me"] as const;

/** The address named a block of Perfil (#privacy): when the guide ends, that block comes back into view. */
function toNamedBlock(): void {
  const id = window.location.hash.slice(1);
  if (!id) return;
  requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
}

/** Where «Ver» takes the reader for the guide of a match: the first match of today's board, else the list. */
function matchPath(qc: QueryClient): string {
  const today = qc.getQueryData<Envelope<Today>>(["v1", "today"])?.data;
  const first = today?.matches?.data?.[0]?.fixture_id;
  return first ? `/matches/${first}` : "/matches";
}

export function GuideProvider({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [active, setActive] = useState<ActiveGuide | null>(null);
  const user = auth.user;

  // what the callbacks read: the values of now, not of the render that made them
  const now = useRef({ user, active, pathname });
  now.current = { user, active, pathname };
  const activePath = useRef<string | null>(null);
  const chain = useRef<Partial<Record<GuideKey, Promise<unknown>>>>({});
  const skips = useRef(0);
  const launchedVisit = useRef(false);
  const requested = useRef<{ guide: GuideKey; from: number } | null>(null);
  const readyScreen = useRef<string | null>(null);
  const returnTo = useRef<HTMLElement | null>(null);

  // The page a visit began on: a visit to another page lets one guide launch by itself again (checked where a screen says it is
  // ready - the page's effect runs before this provider's, so no effect of ours could reset it in time).
  const visit = useRef("");

  const seen = useCallback((guide: GuideKey) => seenOf(now.current.user as Me | null, guide), []);

  /** At once in the page's account; then to the API in order; kept for later when it cannot be sent. */
  const persist = useCallback(
    (guide: GuideKey, body: GuideIn) => {
      const at = new Date().toISOString();
      qc.setQueryData<Me | null>(ME_KEY, (me) =>
        me ? withGuide(me, applied(seenOf(me, guide), guide, body, at)) : me,
      );
      const send = (g: GuideKey, b: GuideIn) =>
        v1.saveGuide(g, b).then((state) => {
          qc.setQueryData<Me | null>(ME_KEY, (me) => (me ? withGuide(me, state) : me));
          return state;
        });
      const before = chain.current[guide] ?? Promise.resolve();
      chain.current[guide] = before.then(() =>
        send(guide, body).then(
          () => {
            dequeue(guide);
            void flush(send);
          },
          () => enqueue(guide, body),
        ),
      );
    },
    [qc],
  );

  // What waited for a connection goes when the account is signed in and the device is back online.
  useEffect(() => {
    if (auth.status !== "signed-in") return;
    const send = (g: GuideKey, b: GuideIn) => v1.saveGuide(g, b);
    void flush(send);
    const online = () => void flush(send);
    window.addEventListener("online", online);
    return () => window.removeEventListener("online", online);
  }, [auth.status]);

  const close = useCallback(() => {
    setActive(null);
    activePath.current = null;
    const back = returnTo.current;
    returnTo.current = null;
    // the focus goes back to where it was; the dialog's own return is unreliable when the card was opened by the page
    if (back && back.isConnected) setTimeout(() => back.focus({ preventScroll: true }), 0);
  }, []);

  const start = useCallback(
    (guide: GuideKey, trigger: Trigger = "replay", from = 0) => {
      const def = GUIDES[guide];
      if (!launchable(def) || now.current.active) return;
      const index = firstFrom(def, from);
      if (index === null) return;
      const resume = trigger === "resume" && from > 0;
      returnTo.current =
        document.activeElement instanceof HTMLElement ? document.activeElement : null;
      activePath.current = now.current.pathname;
      setActive({ key: guide, index, mode: "step", trigger });
      persist(guide, { version: def.version, status: "in_progress", step: index });
      track("guide_started", {
        guide,
        version: def.version,
        trigger: resume ? "resume" : trigger,
      });
    },
    [persist],
  );

  const go = useCallback(
    (index: number) => {
      const current = now.current.active;
      if (!current) return;
      const def = GUIDES[current.key];
      setActive({ ...current, index, mode: "step" });
      persist(current.key, { version: def.version, status: "in_progress", step: index });
    },
    [persist],
  );

  const next = useCallback(() => {
    const current = now.current.active;
    if (!current) return;
    const following = neighbour(GUIDES[current.key], current.index, 1, findAnchor);
    if (following === null) finishRef.current();
    else go(following);
  }, [go]);

  const back = useCallback(() => {
    const current = now.current.active;
    if (!current) return;
    const previous = neighbour(GUIDES[current.key], current.index, -1, findAnchor);
    if (previous !== null) go(previous);
  }, [go]);

  const finish = useCallback(() => {
    const current = now.current.active;
    if (!current) return;
    const def = GUIDES[current.key];
    persist(def.key, { version: def.version, status: "completed", step: current.index });
    // the guide that covers another counts it as seen (Inicio is covered by the general tour)
    for (const other of GUIDE_LIST) {
      if (other.coveredBy === def.key) {
        persist(other.key, { version: other.version, status: "completed", step: 0 });
      }
    }
    track("guide_completed", { guide: def.key, version: def.version });
    skips.current = 0;
    close();
    if (def.key === "profile") toNamedBlock();
  }, [persist, close]);
  const finishRef = useRef(finish);
  finishRef.current = finish;

  const skip = useCallback(
    (method: LeaveMethod = "button") => {
      const current = now.current.active;
      if (!current) return;
      const def = GUIDES[current.key];
      if (def.mandatory) return; // owed: it is paused, never skipped
      persist(def.key, { version: def.version, status: "skipped", step: current.index });
      track("guide_skipped", {
        guide: def.key,
        version: def.version,
        step: current.index,
        method,
      });
      skips.current += 1;
      close();
    },
    [persist, close],
  );

  const pause = useCallback(() => {
    const current = now.current.active;
    if (!current) return;
    const def = GUIDES[current.key];
    persist(def.key, { version: def.version, status: "in_progress", step: current.index });
    track("guide_paused", { guide: def.key, version: def.version, step: current.index });
    close();
    if (def.key === "profile") toNamedBlock();
  }, [persist, close]);

  const dismiss = useCallback(
    (method: LeaveMethod) => {
      const current = now.current.active;
      if (!current) return;
      if (GUIDES[current.key].mandatory) pause();
      else skip(method);
    },
    [pause, skip],
  );

  const resume = useCallback(() => {
    const current = now.current.active;
    if (!current) return;
    setActive({ ...current, mode: "step", trigger: "resume" });
    track("guide_started", {
      guide: current.key,
      version: GUIDES[current.key].version,
      trigger: "resume",
    });
  }, []);

  const declineResume = useCallback(() => {
    // "No, gracias": left as skipped where it was
    skip("button");
  }, [skip]);

  // Moving to another page while a guide is up (the system's back, a link): it ends there - skipped, or paused when owed.
  useEffect(() => {
    if (active && activePath.current !== null && activePath.current !== pathname) {
      dismiss("navigate");
    }
  }, [pathname, active, dismiss]);

  const screenReady = useCallback(
    (screen: string) => {
      const { user: me, active: up, pathname: path } = now.current;
      if (visit.current !== path) {
        visit.current = path;
        launchedVisit.current = false;
      }
      readyScreen.current = screen;
      if (!me) return;
      const ask = requested.current;
      const candidates = GUIDE_LIST.filter((g) => g.screen === screen && launchable(g));
      if (ask) {
        const wanted = GUIDES[ask.guide];
        if (wanted.screen === screen) {
          requested.current = null;
          requestAnimationFrame(() => start(ask.guide, "replay", ask.from));
          return;
        }
      }
      if (up) return;
      const meAccount = me as Me;
      // the first visit to a screen with a guide is recorded even when the guide waits (nothing is shown)
      for (const def of candidates) {
        if (def.key !== "general" && !seenOf(meAccount, def.key)) {
          persist(def.key, { version: def.version, status: "pending", step: 0 });
        }
      }
      for (const def of candidates) {
        const state = seenOf(meAccount, def.key);
        const due = owed(def, state);
        if (!due) continue;
        const facts: Facts = {
          reader: me.role === "USER",
          guidesOn: me.guides_on !== false,
          auto: me.guides_auto !== false,
          welcomeDue: Boolean(me.welcome_due),
          consentsDue: (me.consents_due ?? []).length > 0,
          limited: Boolean(me.membership?.limited),
          fromNotice: originOf() === "notification",
          active: false,
          layerOpen: anotherLayerOpen(),
          launchedThisVisit: launchedVisit.current,
          skipsInARow: skips.current,
        };
        if (blockedBy(def, facts) !== null) continue;
        launchedVisit.current = true;
        requestAnimationFrame(() => {
          if (now.current.pathname !== path || now.current.active) return;
          if (due === "resume") {
            const index = firstFrom(def, state?.step ?? 1, findAnchor);
            if (index === null) return;
            returnTo.current =
              document.activeElement instanceof HTMLElement ? document.activeElement : null;
            activePath.current = path;
            // the owed guide does not ask «¿Seguimos?» (there is no «No»): it goes on from the step it was left at
            if (def.mandatory) {
              setActive({ key: def.key, index, mode: "step", trigger: "resume" });
              track("guide_started", { guide: def.key, version: def.version, trigger: "resume" });
            } else {
              setActive({ key: def.key, index, mode: "resume", trigger: "resume" });
            }
          } else {
            start(def.key, "auto", 0);
          }
        });
        return;
      }
    },
    [persist, start],
  );

  const request = useCallback(
    (guide: GuideKey, from = 0) => {
      const def = GUIDES[guide];
      if (!launchable(def)) return;
      // the guide of a match opens on the first match of today's board (as the old tour did), else the list of matches
      const path = guide === "match" ? matchPath(qc) : def.path;
      requested.current = { guide, from };
      if (now.current.pathname === path && readyScreen.current === def.screen) {
        requested.current = null;
        start(guide, "replay", from);
        return;
      }
      void navigate({ to: path as never });
    },
    [navigate, qc, start],
  );

  const value = useMemo<GuidesValue>(
    () => ({
      active,
      seen,
      start,
      request,
      next,
      back,
      skip,
      finish,
      dismiss,
      resume,
      declineResume,
      screenReady,
    }),
    [
      active,
      seen,
      start,
      request,
      next,
      back,
      skip,
      finish,
      dismiss,
      resume,
      declineResume,
      screenReady,
    ],
  );

  return (
    <GuidesContext.Provider value={value}>
      {children}
      {active ? <GuideLayer /> : null}
    </GuidesContext.Provider>
  );
}
