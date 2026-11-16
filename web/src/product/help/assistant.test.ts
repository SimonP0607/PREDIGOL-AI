/// <reference types="bun" />
/** The assistant as a conversation (UX-149, sheet H02): each question adds what the reader said and the help's answer. */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { FAQ_IDS } from "./faq";
import { answerTo, transcript, type Turn } from "./HelpAssistant";

setLocale("es");

describe("the conversation", () => {
  test("a question the help answers: the reader's words, then the answers with where they come from", () => {
    const turns = answerTo("no me llega el correo", FAQ_IDS);
    expect(turns[0]).toEqual({ who: "me", text: "no me llega el correo" });
    const bot = turns[1]!;
    expect(bot.who).toBe("bot");
    expect(bot.who === "bot" && bot.kind).toBe("found");
  });

  test("a bet request is declined; nothing typed, nothing added", () => {
    expect(answerTo("dame un pick seguro para hoy", FAQ_IDS)[1]).toMatchObject({ kind: "blocked" });
    expect(answerTo("   ", FAQ_IDS)).toEqual([]);
  });

  test("what goes to a person is only what the reader wrote, at most 1000 characters", () => {
    const turns: Turn[] = [
      { who: "me", text: "uno" },
      { who: "bot", kind: "person" },
      { who: "me", text: "dos" },
    ];
    expect(transcript(turns)).toBe("uno\ndos");
    expect(transcript([{ who: "me", text: "x".repeat(2000) }])).toHaveLength(1000);
  });
});
