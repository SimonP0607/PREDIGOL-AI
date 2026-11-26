import { afterEach, describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import {
  ask,
  assistantWords,
  isBlocked,
  MAX_ANSWERS,
  MAX_UNANSWERED_WORDS,
  unansweredTerms,
} from "./helpSearch";
import { FAQ_IDS, faqAnswer, faqQuestion } from "./faq";

afterEach(() => setLocale("es"));

describe("the help's assistant (decision 5): the help's own texts, and nothing else", () => {
  test("an answer is a text of the help, word for word, with where it comes from", () => {
    setLocale("es");
    const r = ask("renovar membresía", FAQ_IDS);
    expect(r.kind).toBe("found");
    if (r.kind !== "found") return;
    expect(r.answers.length).toBeGreaterThan(0);
    expect(r.answers.length).toBeLessThanOrEqual(MAX_ANSWERS);
    for (const a of r.answers) {
      expect(a.origin.length).toBeGreaterThan(0);
      expect(a.hash.length).toBeGreaterThan(0);
      if (a.source === "faq") {
        expect(a.title).toBe(faqQuestion(a.id as (typeof FAQ_IDS)[number]));
        expect(a.text).toBe(faqAnswer(a.id as (typeof FAQ_IDS)[number]));
      }
    }
    expect(r.answers.some((a) => a.source === "faq" && a.id === "renew")).toBe(true);
  });

  test("the glossary and «Cómo funciona» answer too, each saying it is theirs", () => {
    setLocale("es");
    const r = ask("parlay", FAQ_IDS);
    expect(r.kind).toBe("found");
    if (r.kind === "found")
      expect(new Set(r.answers.map((a) => a.source)).size).toBeGreaterThanOrEqual(1);
    const g = ask("hándicap asiático", FAQ_IDS);
    expect(g.kind).toBe("found");
    if (g.kind === "found") expect(g.answers.some((a) => a.source === "glossary")).toBe(true);
  });

  test("a question it cannot answer says so: never half an answer", () => {
    expect(ask("xyzzy plugh", FAQ_IDS)).toEqual({ kind: "none" });
    expect(ask("apodo xyzzy", FAQ_IDS), "a stray word of a body is not an answer").toEqual({
      kind: "none",
    });
    expect(ask("   ", FAQ_IDS)).toEqual({ kind: "empty" });
    expect(ask("¿y?", FAQ_IDS)).toEqual({ kind: "none" });
  });

  test("it never gives a forecast or betting advice, in either language", () => {
    for (const q of [
      "¿Quién gana hoy?",
      "quien va a ganar Nacional o Millonarios",
      "¿Qué apuesto hoy?",
      "a quién le apuesto",
      "dame un pick",
      "Recomiéndame un parlay",
      "apuesta segura para hoy",
      "fijos para mañana",
      "cuánto apuesto",
      "Who will win tonight?",
      "what should I bet",
      "give me a pick",
      "sure bet",
    ]) {
      expect(isBlocked(q), q).toBe(true);
      expect(ask(q, FAQ_IDS), q).toEqual({ kind: "blocked" });
    }
    for (const q of ["qué es un pick", "cómo se liquida un parlay", "what is a pick"])
      expect(isBlocked(q), q).toBe(false);
  });

  test("a question hidden from the page (notices not available) is never an answer", () => {
    const without = FAQ_IDS.filter((id) => id !== "push" && id !== "push_iphone");
    const r = ask("iphone", without);
    if (r.kind === "found")
      expect(r.answers.some((a) => a.source === "faq" && a.id === "push_iphone")).toBe(false);
  });

  test("the words of a question: folded, short ones and filler left out", () => {
    expect(assistantWords("¿Cómo renuevo mi Membresía?")).toEqual(["renuevo", "membresia"]);
  });
});

describe("what the help could not answer is counted by word, never as a question (AP-H02)", () => {
  test("lower-case letters only, without accents or connecting words, each once, three at most", () => {
    expect(unansweredTerms("¿Cómo CANCELO el reembolso del año?")).toEqual([
      "cancelo",
      "reembolso",
      "ano",
    ]);
    expect(unansweredTerms("reembolso reembolso Reembolso")).toEqual(["reembolso"]);
    expect(unansweredTerms("uno dos tres cuatro cinco seis").length).toBe(MAX_UNANSWERED_WORDS);
    expect(unansweredTerms("la el de")).toEqual([]);
    expect(unansweredTerms("")).toEqual([]);
  });

  test("a question with a digit, an address or a link sends nothing at all", () => {
    for (const q of [
      "mi correo es juan@gmail.com y no llega",
      "pedido 12345 no llega",
      "llamen al 3001234567",
      "mira https://example.com/pago",
      "www.example.com no abre",
    ]) {
      expect(unansweredTerms(q), q).toEqual([]);
    }
  });

  test("every word it keeps is one the closed catalog accepts", () => {
    const WORD = /^[a-z]{3,20}$/;
    for (const q of [
      "Pagué con tarjeta débito y nada",
      "I was charged twice, refund please",
      "ñandú extraordinariamente",
    ]) {
      for (const w of unansweredTerms(q)) expect(WORD.test(w), `${q} → ${w}`).toBe(true);
    }
  });
});
