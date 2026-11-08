/**
 * The guides' engine (plan UX-051; PLAN_BIENVENIDA_RECORRIDO, sections 3, 7 and 11): one guide at a time, whatever launched it.
 *
 * Replaces the optional tour and the first-visit hints of A13. A screen says it has its data (`useGuideScreen`); the guide that
 * opens on it launches by itself once, unless something stands in its way (eligibility.ts: the rules against fatigue) or the
 * reader asked for it ("?", Ayuda). Everything the reader does is recorded: at once in the account the page holds, then in the
 * API (one write at a time per guide, in order) - a write that cannot be sent waits in this device's queue (queue.ts), one per
 * account, and goes the next time; meanwhile the page counts it, so the guide does not come back. The survey and the offer of
 * notices wait while a guide is up (`active`).
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { v1 } from "@/lib/api/v1/client";
import type { Me } from "@/lib/api/v1/types_auth";
import type { Envelope } from "@/lib/api/v1/types";
import type { Today } from "@/lib/api/v1/types_today";
import type { GuideIn, GuideKey, GuideState } from "@/lib/api/v1/types_guides";
import { live } from "@/lib/api/v1/queries";
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
import { dequeue, dropLegacy, enqueue, flush, readQueue, refused, type Owner } from "./queue";
import { GUIDES, GUIDE_LIST, launchable } from "./registry";
import { applied, seenOf, withGuide } from "./state";

const ME_KEY = ["auth", "me"] as const;

/** The address named a block of Perfil (#privacy): when the guide ends, that block comes back into view. */
function toNamedBlock(): void {
  const id = window.location.hash.slice(1);
  if (!id) return;
  requestAnimationFrame(() => document.getElementById(id)?.scrollIntoView({ block: "start" }));
}

/** Where «Ver» takes the reader for the guide of a match: the first match of today's board (asked for when the page does not
 * have it yet: Ayuda opened directly), else the list. */
async function matchPath(qc: QueryClient): Promise<string> {
  const firstOf = (board: Envelope<Today> | undefined) =>
    board?.data?.matches?.data?.[0]?.fixture_id;
  let first = firstOf(qc.getQueryData<Envelope<Today>>(["v1", "today"]));
  if (!first) {
    try {
      first = firstOf(await qc.fetchQuery({ ...live.today, staleTime: 60_000 }));
    } catch {
      // no board: the list
    }
  }
  return first ? `/matches/${first}` : "/matches";
}

/** A match's own page (its tabs are in the search, never in the path). */
const MATCH_PAGE = /^\/matches\/\d+\/?$/;

/** Who may be shown a guide at all: a reader's account, with the guides on (FBI_GUIDES). */
function showsGuides(me: Me | null): me is Me {
  return Boolean(me && me.role === "USER" && me.guides_on !== false);
}

/** The rules of a write put over a state (the server's own: within a version the status never goes down). */
function over(state: GuideState | undefined, guide: GuideKey, body: GuideIn | undefined) {
  return body ? applied(state, guide, body, new Date().toISOString()) : state;
}

const asWrite = (state: GuideState): GuideIn => ({
  version: state.version,
  status: state.status,
  step: state.step,
});

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

  // What this page wrote for the account, folded by the server's rules (UX-070). The account the page holds can lag behind:
  // an answer, or a reading of /auth/me that left before the write, may come after the screen asks what is owed. A guide
  // the reader already skipped or finished here must not come back for that.
  const wrote = useRef<{ owner: Owner | undefined; states: Partial<Record<GuideKey, GuideState>> }>(
    {
      owner: undefined,
      states: {},
    },
  );
  const remember = useCallback((owner: Owner, guide: GuideKey, body: GuideIn) => {
    if (wrote.current.owner !== owner) wrote.current = { owner, states: {} };
    wrote.current.states[guide] = applied(
      wrote.current.states[guide],
      guide,
      body,
      new Date().toISOString(),
    );
  }, []);

  /**
   * What the page knows of a guide for the account: the API's state, with what this page wrote and what still waits in the
   * device's queue applied (UX-070) - a write not yet answered, or one that could not be sent, never brings the guide back,
   * on the next visit or after a reload.
   */
  const seenNow = useCallback((me: Me | null, guide: GuideKey): GuideState | undefined => {
    const recorded = seenOf(me, guide);
    if (!me) return recorded;
    const queued = over(recorded, guide, readQueue(me.id)[guide]);
    const mine = wrote.current.owner === me.id ? wrote.current.states[guide] : undefined;
    return mine ? over(queued, guide, asWrite(mine)) : queued;
  }, []);

  const seen = useCallback((guide: GuideKey) => seenNow(now.current.user, guide), [seenNow]);

  /** A write for one account, its answer put in the page's account only while that account is still the one signed in. */
  const sendFor = useCallback(
    (owner: Owner) => (g: GuideKey, b: GuideIn) => {
      remember(owner, g, b);
      return v1.saveGuide(g, b).then((state) => {
        qc.setQueryData<Me | null>(ME_KEY, (me) =>
          me && me.id === owner ? withGuide(me, state) : me,
        );
        return state;
      });
    },
    [qc, remember],
  );

  /** At once in the page's account; then to the API in order; kept for later when it cannot be sent. */
  const persist = useCallback(
    (guide: GuideKey, body: GuideIn) => {
      // the account that did it: its write, its queue - whoever is signed in when the answer comes (UX-070)
      const owner = now.current.user?.id;
      if (owner === undefined) return;
      remember(owner, guide, body);
      const at = new Date().toISOString();
      qc.setQueryData<Me | null>(ME_KEY, (me) =>
        me && me.id === owner ? withGuide(me, applied(seenOf(me, guide), guide, body, at)) : me,
      );
      const send = sendFor(owner);
      const before = chain.current[guide] ?? Promise.resolve();
      chain.current[guide] = before.then(() =>
        send(guide, body).then(
          () => {
            dequeue(owner, guide);
            void flush(owner, send);
          },
          (err: unknown) => {
            // a write the API turned down for good is not kept: sent again it would only fail again
            if (!refused(err)) enqueue(owner, guide, body);
          },
        ),
      );
    },
    [qc, remember, sendFor],
  );

  // What waited for a connection goes when its own account is signed in and the device is back online.
  const userId = user?.id;
  useEffect(() => {
    if (auth.status !== "signed-in" || userId === undefined) return;
    dropLegacy();
    const send = sendFor(userId);
    void flush(userId, send);
    const online = () => void flush(userId, send);
    window.addEventListener("online", online);
    return () => window.removeEventListener("online", online);
  }, [auth.status, userId, sendFor]);

  // The account signed out (or another took its place): what this session counted and asked for was that account's.
  const lastUser = useRef(userId);
  useEffect(() => {
    const before = lastUser.current;
    lastUser.current = userId;
    if (before === undefined || before === userId) return;
    skips.current = 0;
    requested.current = null;
    launchedVisit.current = false;
    activePath.current = null;
    setActive(null);
  }, [userId]);

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
      if (!launchable(def) || now.current.active || !showsGuides(now.current.user)) return;
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

  // A guide that waited only because another layer was open goes on once the layer is closed, on the same page (UX-070).
  const readyRef = useRef<(screen: string) => void>(() => undefined);
  const layerWatch = useRef<MutationObserver | null>(null);
  const stopWatch = useCallback(() => {
    layerWatch.current?.disconnect();
    layerWatch.current = null;
  }, []);
  const watchLayers = useCallback(
    (screen: string, path: string) => {
      if (layerWatch.current || typeof MutationObserver === "undefined") return;
      const observer = new MutationObserver(() => {
        if (now.current.pathname !== path) {
          stopWatch();
          return;
        }
        if (anotherLayerOpen()) return;
        stopWatch();
        readyRef.current(screen);
      });
      observer.observe(document.body, {
        subtree: true,
        childList: true,
        attributes: true,
        attributeFilter: ["data-state"],
      });
      layerWatch.current = observer;
    },
    [stopWatch],
  );
  // another page: what the last one waited for is gone with it
  useEffect(() => stopWatch, [pathname, stopWatch]);

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
        // a request is for the screen it led to: on any other it is gone, never left to come up later (UX-070)
        requested.current = null;
        if (GUIDES[ask.guide].screen === screen) {
          requestAnimationFrame(() => start(ask.guide, "replay", ask.from));
          return;
        }
      }
      if (up) return;
      // the owner's account is shown no guide, and nothing of its visits is recorded for one
      if (me.role !== "USER") return;
      // the first visit to a screen with a guide is recorded even when the guide waits (nothing is shown)
      for (const def of candidates) {
        if (def.key !== "general" && !seenNow(me, def.key)) {
          persist(def.key, { version: def.version, status: "pending", step: 0 });
        }
      }
      let layerOpen = false;
      for (const def of candidates) {
        const state = seenNow(me, def.key);
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
        const reason = blockedBy(def, facts);
        if (reason === "layer-open") layerOpen = true;
        if (reason !== null) continue;
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
      if (layerOpen) watchLayers(screen, path);
    },
    [persist, seenNow, start, watchLayers],
  );
  readyRef.current = screenReady;

  const request = useCallback(
    (guide: GuideKey, from = 0) => {
      const def = GUIDES[guide];
      if (!launchable(def)) return;
      if (!showsGuides(now.current.user)) {
        // no guide for this account (the owner's, FBI_GUIDES=0): the reader still goes where they asked to
        if (now.current.pathname !== def.path) void navigate({ to: def.path as never });
        return;
      }
      if (
        guide === "match" &&
        readyScreen.current === "match" &&
        MATCH_PAGE.test(now.current.pathname)
      ) {
        start(guide, "replay", from);
        return;
      }
      void (async () => {
        // the guide of a match opens on the first match of today's board (as the old tour did); with no match, the list of
        // matches - and nothing is left waiting to come up on a match opened later (UX-070)
        const path = guide === "match" ? await matchPath(qc) : def.path;
        if (guide === "match" && !MATCH_PAGE.test(path)) {
          requested.current = null;
          void navigate({ to: path as never });
          return;
        }
        requested.current = { guide, from };
        if (now.current.pathname === path && readyScreen.current === def.screen) {
          requested.current = null;
          start(guide, "replay", from);
          return;
        }
        void navigate({ to: path as never });
      })();
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
