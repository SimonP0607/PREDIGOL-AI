/// <reference types="bun" />
/**
 * The notices' pieces a reader sees (plan UX, B7; sections 34 and 35), without a browser: when the offer may come (never
 * on opening - only after a moment -, never twice a visit, never over another card, never to a blocked browser, never
 * again for 30 days after «Ahora no»); the offer's card says what would arrive and its limits, with «Ahora no» beside
 * «Activar avisos», and on an iPhone in Safari shows how to install PrediGol instead; the bell rings only for a match
 * that starts within 7 days; the profile's block shows this browser's state and how to allow a blocked one, the four
 * categories, the devices with «este dispositivo» and «Quitar», and the test only when a device receives; and the
 * owner's card counts devices and notices, never who.
 */
import { afterAll, describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import { setLocale, t } from "@/lib/i18n";
import type { PushOverview, PushState } from "@/lib/api/v1/types_push";
import type { DeviceStatus } from "@/lib/push";
import { PushView } from "@/admin/PushCard";
import { PushSectionView } from "@/product/profile/PushSection";
import { InstallGuide } from "./InstallGuide";
import { PushOfferView, type OfferPhase } from "./PushOffer";
import {
  LATER_DAYS,
  bellOffered,
  markLater,
  mayOfferPush,
  saidLater,
  type OfferFacts,
  type PushMoment,
} from "./moments";

afterAll(() => setLocale("es"));

const noop = () => {};

const STATE: PushState = {
  available: true,
  public_key: "BPublicKey",
  devices: [
    {
      id: 41,
      family: "chrome",
      system: "android",
      installed: true,
      created_at: "2026-10-20T12:00:00Z",
      last_ok_at: "2026-10-27T11:00:00Z",
    },
    {
      id: 7,
      family: "safari",
      system: "ios",
      installed: true,
      created_at: "2026-10-21T12:00:00Z",
      last_ok_at: null,
    },
  ],
  categories: { result: true, lineup: true, digest: false, account: true },
  quiet_start: "22:00",
  quiet_end: "08:00",
  daily_cap: 3,
};

/** The opening tag of the element with this test id. */
function tag(out: string, testId: string): string {
  return new RegExp(`<[a-z]+[^>]*data-testid="${testId}"[^>]*>`).exec(out)?.[0] ?? "";
}

function text(out: string): string {
  return out
    .replace(/<[^>]+>/g, " ")
    .replace(/&#x27;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ");
}

const FACTS: OfferFacts = {
  reader: true,
  available: true,
  device: "off",
  hasDevices: false,
  later: false,
  asked: false,
  tour: false,
};

describe("when the offer may come", () => {
  test("after a moment, to a reader whose browser could receive and does not yet", () => {
    expect(mayOfferPush(FACTS)).toBe(true);
  });

  test.each([
    ["the owner", { reader: false }],
    ["notices not available (no key, P12)", { available: false }],
    ["«Ahora no» in the last 30 days", { later: true }],
    ["something already asked in this visit", { asked: true }],
    ["the tour's card up", { tour: true }],
    ["this browser already receives", { device: "on" }],
    ["this browser blocked them", { device: "denied" }],
    ["this browser cannot", { device: "unsupported" }],
    ["this browser still being found out", { device: null }],
  ] as const)("never with %s", (_why, change) => {
    expect(mayOfferPush({ ...FACTS, ...change } as OfferFacts)).toBe(false);
  });

  test("an iPhone in Safari: the install guide - unless the account already receives on another device", () => {
    expect(mayOfferPush({ ...FACTS, device: "needs_install" })).toBe(true);
    expect(mayOfferPush({ ...FACTS, device: "needs_install", hasDevices: true })).toBe(false);
  });

  test("«Ahora no» keeps it away for 30 days on this device, then it may come again", () => {
    const store = new Map<string, string>();
    const fake = {
      getItem: (k: string) => store.get(k) ?? null,
      setItem: (k: string, v: string) => void store.set(k, v),
    };
    const day = new Date("2026-10-27T15:00:00Z");
    expect(saidLater(day, fake)).toBe(false);
    markLater(day, fake);
    expect(saidLater(new Date(day.getTime() + (LATER_DAYS - 1) * 86_400_000), fake)).toBe(true);
    expect(saidLater(new Date(day.getTime() + LATER_DAYS * 86_400_000), fake)).toBe(false);
    expect(saidLater(day, null)).toBe(false);
  });

  test("the bell rings only for a match that starts in the future, within 7 days", () => {
    const now = Date.parse("2026-10-27T15:00:00Z");
    expect(bellOffered("2026-10-27T15:30:00Z", now)).toBe(true);
    expect(bellOffered("2026-11-03T15:00:00Z", now)).toBe(true);
    expect(bellOffered("2026-11-03T15:00:01Z", now)).toBe(false);
    expect(bellOffered("2026-10-27T14:59:00Z", now)).toBe(false);
    expect(bellOffered("not a date", now)).toBe(false);
  });
});

function offer(moment: PushMoment, phase: OfferPhase): string {
  return renderToStaticMarkup(
    <PushOfferView
      moment={moment}
      phase={phase}
      rules={STATE}
      onEnable={noop}
      onLater={noop}
      onClose={noop}
    />,
  );
}

describe("the offer's card", () => {
  test("it says what would arrive and its limits, «Ahora no» beside «Activar avisos»; not modal", () => {
    const out = offer({ reason: "follow", team: "Millonarios" }, "ask");
    expect(tag(out, "push-offer")).toContain('aria-modal="false"');
    expect(text(out)).toContain(t("push.offer.follow.title", { team: "Millonarios" }));
    expect(text(out)).toContain(t("push.offer.rules", { from: "22:00", to: "08:00", cap: 3 }));
    expect(out).toContain('data-testid="push-offer-later"');
    expect(out).toContain('data-testid="push-offer-enable"');
    expect(text(offer({ reason: "save" }, "ask"))).toContain(t("push.offer.save.title"));
  });

  test("on an iPhone in Safari: how to install PrediGol, no button that cannot work", () => {
    const out = offer({ reason: "save" }, "install");
    expect(out).toContain('data-testid="install-guide"');
    expect(out).not.toContain('data-testid="push-offer-enable"');
    expect(text(out)).toContain(t("push.install.iosStep2"));
  });

  test("after the browser's answer: done, blocked (and where to allow it) or failed - and a way to close", () => {
    for (const phase of ["done", "denied", "failed"] as const) {
      const out = offer({ reason: "save" }, phase);
      expect(text(out)).toContain(t(`push.offer.${phase}`));
      expect(out).toContain('data-testid="push-offer-ok"');
    }
  });

  test("in English too", () => {
    setLocale("en");
    const out = offer({ reason: "follow", team: "Millonarios" }, "ask");
    expect(text(out)).toContain("Shall we tell you when Millonarios's line-ups are out?");
    expect(text(out)).toContain("Not now");
    setLocale("es");
  });
});

describe("the guided install", () => {
  test("an iPhone: the three steps and the iOS version; anywhere else: the basic steps", () => {
    const ios = renderToStaticMarkup(<InstallGuide platform="ios" />);
    expect(text(ios)).toContain(t("push.install.iosStep1"));
    expect(text(ios)).toContain(t("push.install.iosStep3Notices"));
    expect(text(ios)).toContain(t("push.install.iosVersion"));
    const android = renderToStaticMarkup(<InstallGuide platform="android" />);
    expect(text(android)).toContain(t("nav.install.android"));
    expect(android).not.toContain('data-testid="install-prompt"');
  });
});

function section(
  here: DeviceStatus | null,
  state: PushState = STATE,
  hereId: number | null = null,
) {
  return renderToStaticMarkup(
    <PushSectionView
      state={state}
      here={here}
      hereId={hereId}
      busy={null}
      failure={null}
      onEnable={noop}
      onDisable={noop}
      onToggle={noop}
      onRemove={noop}
      onTest={noop}
    />,
  );
}

describe("the profile's block", () => {
  test("this browser's state, with the action that fits it", () => {
    expect(section("off")).toContain('data-testid="push-enable"');
    expect(section("off")).not.toContain('data-testid="push-disable"');
    expect(section("on", STATE, 41)).toContain('data-testid="push-disable"');
    expect(text(section("denied"))).toContain(t("push.profile.status.denied"));
    expect(section("denied")).not.toContain('data-testid="push-enable"');
    expect(section("needs_install")).toContain('data-testid="install-guide"');
    expect(text(section("unsupported"))).toContain(t("push.profile.status.unsupported"));
  });

  test("the four categories as switches, each saying what it is", () => {
    const out = section("off");
    for (const [c, on] of Object.entries(STATE.categories)) {
      const row = new RegExp(
        `data-testid="push-category-${c}"[^]*?role="switch"[^>]*aria-checked="${on}"`,
      );
      expect(row.test(out)).toBe(true);
      expect(text(out)).toContain(t(`push.profile.categoryHelp.${c}`));
    }
  });

  test("the devices, this one marked, each with «Quitar»; the test only when a device receives", () => {
    const out = section("on", STATE, 41);
    expect(out.match(/data-testid="push-device"/g)?.length).toBe(2);
    expect(text(out)).toContain("Chrome en Android");
    expect(text(out)).toContain("Safari en iPhone o iPad");
    expect(text(out)).toContain(t("push.profile.here"));
    expect(text(out)).toContain(t("push.profile.never"));
    expect(out.match(/data-testid="push-device-remove"/g)?.length).toBe(2);
    expect(out).toContain('data-testid="push-test"');
    const none = section("off", { ...STATE, devices: [] });
    expect(none).toContain('data-testid="push-no-devices"');
    expect(none).not.toContain('data-testid="push-test"');
  });

  test("the rules: the quiet hours and the daily ceiling, from the server", () => {
    expect(text(section("off"))).toContain(
      t("push.profile.help", { from: "22:00", to: "08:00", cap: 3 }),
    );
  });
});

describe("the owner's card", () => {
  const overview: PushOverview = {
    available: false,
    readers: 3,
    devices: [
      { family: "chrome", system: "android", devices: 3 },
      { family: "safari", system: "ios", devices: 1 },
    ],
    notices: [
      { category: "result", sent: 12, dropped: 2 },
      { category: "reminder", sent: 4, dropped: 0 },
    ],
    gone: 1,
  };

  test("available or not, readers and devices, a week of notices by kind - counts, never who", () => {
    const out = renderToStaticMarkup(<PushView o={overview} />);
    expect(text(out)).toContain(t("admin.product.push.off"));
    const devices = /data-testid="push-devices"[^]*?<\/div>/.exec(out)?.[0] ?? "";
    expect(text(devices)).toContain("4");
    expect(text(out)).toContain(t("admin.product.push.categories.result"));
    expect(text(out)).toContain("12");
    expect(out).not.toMatch(/@|user_id|endpoint/);
  });
});
