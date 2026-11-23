/// <reference types="bun" />
/** AP-H01 (finding H3): no answer of the help or of its assistant names a channel that is not published. */
import { afterEach, describe, expect, test } from "bun:test";
import type { SupportContact } from "@/lib/api/v1/types_support";
import { setLocale, t } from "@/lib/i18n";
import { FAQ_IDS, faqAnswer } from "./faq";
import { answerTo } from "./HelpAssistant";
import { ask } from "./helpSearch";
import { NO_REACH, reachKey, reachOf, reachPhrase } from "./reach";

afterEach(() => setLocale("es"));

function contact(patch: Partial<SupportContact>): SupportContact {
  return {
    whatsapp: null,
    email: null,
    channels: [],
    hours: null,
    ...patch,
  };
}

const WITH_WHATSAPP = reachOf(
  contact({
    whatsapp: "573001234567",
    email: "ayuda@example.com",
    channels: ["whatsapp", "email"],
  }),
);
const WITHOUT_WHATSAPP = reachOf(
  contact({ email: "ayuda@example.com", channels: ["tickets", "email"] }),
);

describe("which channels are published", () => {
  test("a number or address that exists AND the owner's list keeps", () => {
    expect(WITH_WHATSAPP).toEqual({ whatsapp: true, email: true });
    expect(WITHOUT_WHATSAPP).toEqual({ whatsapp: false, email: true });
    expect(reachOf(contact({ whatsapp: "57300", channels: ["tickets"] }))).toEqual(NO_REACH);
    expect(
      reachOf(contact({ whatsapp: "57300" })).whatsapp,
      "an older answer without the list",
    ).toBe(true);
    expect(reachOf(null)).toEqual(NO_REACH);
    expect(reachOf(undefined)).toEqual(NO_REACH);
  });

  test("the four phrases", () => {
    expect(reachKey(WITH_WHATSAPP)).toBe("both");
    expect(reachKey({ whatsapp: true, email: false })).toBe("whatsapp");
    expect(reachKey(WITHOUT_WHATSAPP)).toBe("email");
    expect(reachKey(NO_REACH)).toBe("none");
  });
});

describe("the answers name only the channels that are published", () => {
  const cases = [
    ["without WhatsApp", WITHOUT_WHATSAPP, false],
    ["with nothing published", NO_REACH, false],
    ["with WhatsApp", WITH_WHATSAPP, true],
  ] as const;

  for (const locale of ["es", "en"] as const) {
    for (const [label, reach, named] of cases) {
      test(`${locale}: every answer ${label}`, () => {
        setLocale(locale);
        for (const id of FAQ_IDS) {
          const text = faqAnswer(id, reach);
          expect(text, id).not.toContain("{reach}");
          if (!named) expect(text, id).not.toMatch(/whatsapp/i);
        }
        // the two answers that send the reader to write to us
        expect(/whatsapp/i.test(faqAnswer("renew", reach))).toBe(named);
        expect(/whatsapp/i.test(faqAnswer("cant_sign_in", reach))).toBe(named);
      });
    }
  }

  test("without WhatsApp the answer points inside the app", () => {
    setLocale("es");
    const text = faqAnswer("renew", WITHOUT_WHATSAPP);
    expect(text).toContain("escríbenos por correo");
    const none = faqAnswer("renew", NO_REACH);
    expect(none).toContain("Ayuda → «Hablar con una persona»");
    expect(none).toContain(t("support.help.actions.person"));
    expect(reachPhrase(NO_REACH)).toContain("Hablar con una persona");
  });

  test("the e-mail is not named when it is not published", () => {
    setLocale("es");
    expect(faqAnswer("cant_sign_in", NO_REACH)).not.toMatch(/por correo \(/);
    expect(reachPhrase({ whatsapp: true, email: false })).not.toMatch(/correo/);
  });

  test("the assistant answers with the same words: no channel that is absent", () => {
    setLocale("es");
    for (const reach of [WITHOUT_WHATSAPP, NO_REACH]) {
      const r = ask("renovar membresía", FAQ_IDS, reach);
      expect(r.kind).toBe("found");
      if (r.kind !== "found") continue;
      for (const a of r.answers) expect(a.text).not.toMatch(/whatsapp/i);
      const turns = answerTo("no puedo entrar a mi cuenta", FAQ_IDS, reach);
      const bot = turns[1]!;
      expect(bot.who === "bot" && bot.kind).toBe("found");
      if (bot.who === "bot" && bot.kind === "found")
        for (const a of bot.answers) expect(a.text).not.toMatch(/whatsapp/i);
    }
    const r = ask("renovar membresía", FAQ_IDS, WITH_WHATSAPP);
    expect(r.kind === "found" && r.answers.some((a) => /whatsapp/i.test(a.text))).toBe(true);
  });

  test("the contact notices do not name WhatsApp when it is not there", () => {
    for (const locale of ["es", "en"] as const) {
      setLocale(locale);
      for (const key of ["support.help.contact.off", "support.ticket.readOnly"]) {
        const text = t(key, { reach: reachPhrase(WITHOUT_WHATSAPP) });
        expect(text, key).not.toMatch(/whatsapp/i);
        expect(text, key).not.toContain("{reach}");
      }
      expect(t("support.help.channels.telegramNote")).not.toMatch(/whatsapp/i);
      expect(t("errors.too_many_tickets")).not.toMatch(/whatsapp/i);
    }
  });
});
