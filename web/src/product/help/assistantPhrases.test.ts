/// <reference types="bun" />
/**
 * 60 phrases readers write (plan AP-H02): at least nine in ten lead to an answer of the help, a step-by-step flow or a
 * greeting; the rest lead to suggestions and a person - never to an error. Each phrase says where it should lead.
 */
import { describe, expect, test } from "bun:test";
import { setLocale } from "@/lib/i18n";
import { FAQ_IDS, type FaqId } from "./faq";
import { answerTo, follow, type Turn } from "./HelpAssistant";
import { FLOWS, smalltalkOf, flowOf } from "./assistantFlows";
import { nearly } from "./helpSearch";

setLocale("es");

type Expect =
  | { faq: FaqId }
  | { flow: string }
  | { talk: "greeting" | "thanks" | "bye" }
  | { menu: true }
  | { blocked: true }
  | { suggest: true };

const PHRASES: readonly (readonly [string, Expect])[] = [
  ["hola", { talk: "greeting" }],
  ["Buenas tardes", { talk: "greeting" }],
  ["hello", { talk: "greeting" }],
  ["gracias", { talk: "thanks" }],
  ["muchas gracias!", { talk: "thanks" }],
  ["chao", { talk: "bye" }],
  ["ayuda", { menu: true }],
  ["menú", { menu: true }],
  ["no puedo entrar", { flow: "signin" }],
  ["no me deja ingresar a mi cuenta", { flow: "signin" }],
  ["can't sign in", { flow: "signin" }],
  ["no veo picks", { flow: "nopicks" }],
  ["no hay picks hoy", { flow: "nopicks" }],
  ["quiero pagar", { flow: "pay" }],
  ["como renovar", { flow: "pay" }],
  ["membresia", { faq: "renew" }],
  ["olvide mi clave", { faq: "cant_sign_in" }],
  ["no me llega el correo", { faq: "emails" }],
  ["cómo renuevo mi membresía", { faq: "renew" }],
  ["como renuebo mi membresia", { faq: "renew" }],
  ["cuando termina mi membresia", { faq: "membership_ends" }],
  ["prueba gratis", { faq: "trial" }],
  ["como borro mi cuenta", { faq: "delete_account" }],
  ["eliminar cuenta", { faq: "delete_account" }],
  ["que datos guardan de mi", { faq: "my_data" }],
  ["que es un pick", { faq: "what_pick" }],
  ["por que hoy no hay pick", { flow: "nopicks" }],
  ["diferencia entre pronostico y pick", { faq: "forecast_pick" }],
  ["garantizan que voy a ganar", { faq: "guarantee" }],
  ["como funciona un parlay", { faq: "parlay" }],
  ["combinada", { faq: "parlay" }],
  ["cuando se liquida un pick", { faq: "when_settled" }],
  ["que significa anulado", { faq: "void_half" }],
  ["medio ganado", { faq: "void_half" }],
  ["que son las unidades", { faq: "units" }],
  ["verificacion en dos pasos", { faq: "two_steps" }],
  ["cambiar idioma", { faq: "language_zone" }],
  ["zona horaria", { faq: "language_zone" }],
  ["instalar en el celular", { faq: "install" }],
  ["avisos en el telefono", { faq: "push" }],
  ["no me llegan los avisos en iphone", { faq: "push_iphone" }],
  ["tu seleccion", { faq: "own_selection" }],
  ["que es prediGol", { faq: "what_is" }],
  ["debo apostar", { faq: "should_bet" }],
  ["siento que el juego me hace daño", { faq: "get_help" }],
  ["que se envia cuando reporto un problema", { faq: "report_context" }],
  ["dame un pick seguro", { blocked: true }],
  ["quien gana hoy", { blocked: true }],
  ["que apuesto", { blocked: true }],
  ["what should I bet", { blocked: true }],
  ["asdfgh qwerty", { suggest: true }],
  ["xyzzy plugh", { suggest: true }],
  ["cuanto cuesta", { faq: "renew" }],
  ["quiero hablar con alguien", { suggest: true }],
  ["mi perro se llama rocky", { suggest: true }],
  ["hola buenas, no puedo entrar", { flow: "signin" }],
  ["contraseña olvidada", { faq: "cant_sign_in" }],
  ["membrecia", { faq: "renew" }],
  ["notificaciones", { faq: "push" }],
  ["borrar mis datos", { faq: "delete_account" }],
];

function outcome(turns: Turn[], expected: Expect): boolean {
  const bot = turns[1];
  if (!bot || bot.who !== "bot") return false;
  if ("faq" in expected)
    return (
      bot.kind === "found" && bot.answers.some((a) => a.source === "faq" && a.id === expected.faq)
    );
  if ("flow" in expected) return bot.kind === "flow" && bot.flow === expected.flow;
  if ("talk" in expected) return bot.kind === expected.talk;
  if ("menu" in expected) return bot.kind === "menu";
  if ("blocked" in expected) return bot.kind === "blocked";
  return bot.kind === "none" && bot.suggest.length === 3;
}

describe("60 phrases readers write", () => {
  test("nine in ten lead where they should; none is an error", () => {
    expect(PHRASES.length).toBe(60);
    const missed: string[] = [];
    for (const [phrase, expected] of PHRASES) {
      const turns = answerTo(phrase, FAQ_IDS);
      expect(turns.length, phrase).toBe(2);
      if (!outcome(turns, expected)) missed.push(phrase);
    }
    expect(missed, `missed: ${missed.join(" | ")}`).toEqual(expect.any(Array));
    expect(
      (PHRASES.length - missed.length) / PHRASES.length,
      missed.join(" | "),
    ).toBeGreaterThanOrEqual(0.9);
  });

  test("a phrase that finds nothing offers three questions and a person, in that order", () => {
    const [, bot] = answerTo("mi perro se llama rocky", FAQ_IDS);
    expect(bot).toMatchObject({ kind: "none" });
    expect(bot?.who === "bot" && bot.kind === "none" && bot.suggest).toEqual([
      "cant_sign_in",
      "renew",
      "no_pick",
    ]);
  });

  test("a bet request never starts a flow", () => {
    expect(answerTo("quiero un pick para pagar mis deudas", FAQ_IDS)[1]).toMatchObject({
      kind: "blocked",
    });
  });
});

describe("the flows", () => {
  test("every button of every step leads somewhere that exists", () => {
    for (const flow of FLOWS) {
      expect(flow.steps["start"], flow.id).toBeDefined();
      for (const [stepId, step] of Object.entries(flow.steps)) {
        expect(step.options.length, `${flow.id}.${stepId}`).toBeGreaterThanOrEqual(2);
        for (const option of step.options) {
          const turn = follow(option.next, FAQ_IDS, undefined, flow.id);
          expect(turn, `${flow.id}.${stepId}.${option.id}`).not.toBeNull();
          if (turn?.who === "bot" && turn.kind === "flow")
            expect(flow.steps[turn.step], `${flow.id} → ${turn.step}`).toBeDefined();
        }
      }
    }
  });

  test("a step that leads to a question the page does not show says nothing instead of failing", () => {
    expect(
      follow(
        { faq: "push" },
        FAQ_IDS.filter((id) => id !== "push"),
      ),
    ).toBeNull();
  });

  test("small talk is only small talk: a question with a greeting in it is a question", () => {
    expect(smalltalkOf("hola")).toBe("greeting");
    expect(smalltalkOf("hola como renuevo")).toBeNull();
    expect(flowOf("hola buenas, no puedo entrar")?.id).toBe("signin");
  });

  test("a typo of one letter is still the word", () => {
    expect(nearly("renuebo", "renuevo")).toBe(true);
    expect(nearly("membrecia", "membresia")).toBe(true);
    expect(nearly("membersia", "membresia")).toBe(true);
    expect(nearly("pick", "picks")).toBe(true);
    expect(nearly("correo", "carrer")).toBe(false);
  });
});
