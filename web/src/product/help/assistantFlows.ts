/**
 * What the help's assistant does besides searching (plan AP-H02, finding H1): it answers a greeting, a thanks and a
 * goodbye; it offers the topics of the help as buttons; and for the three things readers ask most - «no puedo entrar»,
 * «no veo picks», «quiero pagar» - it walks them through by steps, each step a question with buttons.
 *
 * Nothing here is generated and nothing calls an AI: a flow ends in one of the help's own answers (a question of the FAQ),
 * in a person, or in another step. The words live in the catalogue (support.assistant.*); this file says which topics,
 * flows and steps there are and where each button leads. The assistant never names a channel that is not published: the
 * answers it ends in already follow AP-H01.
 */
import { fold } from "@/lib/glossary";
import type { FaqId } from "./faq";

export type Smalltalk = "greeting" | "thanks" | "bye";

const SMALLTALK: Record<Smalltalk, readonly string[]> = {
  greeting: [
    "hola",
    "holaa",
    "holi",
    "buenas",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "buen dia",
    "hey",
    "hello",
    "hi",
    "good morning",
    "good afternoon",
    "good evening",
    "saludos",
  ],
  thanks: [
    "gracias",
    "muchas gracias",
    "mil gracias",
    "gracias por todo",
    "thanks",
    "thank you",
    "thanks a lot",
    "ty",
  ],
  bye: ["chao", "chau", "adios", "hasta luego", "nos vemos", "bye", "goodbye", "see you"],
};

function plain(query: string): string {
  return fold(query)
    .replace(/[^a-z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** A greeting, a thanks or a goodbye - and nothing else in the message - or null. */
export function smalltalkOf(query: string): Smalltalk | null {
  const text = plain(query);
  if (text.length === 0) return null;
  for (const kind of ["greeting", "thanks", "bye"] as const) {
    if (SMALLTALK[kind].includes(text)) return kind;
  }
  return null;
}

/** The topics of the menu (the plan's eight): which questions of the help each one opens. */
export const TOPICS = [
  { id: "account", faq: ["cant_sign_in", "two_steps", "language_zone"] },
  { id: "membership", faq: ["renew", "membership_ends", "trial"] },
  { id: "picks", faq: ["what_pick", "no_pick", "forecast_pick", "own_selection"] },
  { id: "parlays", faq: ["parlay", "when_settled", "void_half", "units"] },
  { id: "odds", faq: ["guarantee", "should_bet"] },
  { id: "notices", faq: ["emails", "push", "push_iphone", "install"] },
  { id: "privacy", faq: ["my_data", "delete_account", "report_context"] },
] as const satisfies readonly { id: string; faq: readonly FaqId[] }[];

export type TopicId = (typeof TOPICS)[number]["id"];

/** «hablar con una persona» is the last button of the menu: it is not a topic, it ends the conversation with a person. */
export const PERSON_TOPIC = "person";

/** Whether the reader asked for the menu itself: «ayuda», «menú», «temas», «opciones». */
export function wantsMenu(query: string): boolean {
  return /^(ayuda|ayudame|help|menu|temas|opciones|topics|options|que puedes hacer|what can you do)$/.test(
    plain(query),
  );
}

export type FlowId = "signin" | "nopicks" | "pay";

export type Next = { faq: FaqId } | { step: string } | { person: true } | { topic: TopicId };

export interface FlowStep {
  /** The buttons, in order: their labels are support.assistant.flows.<flow>.<step>.<option>. */
  options: readonly { id: string; next: Next }[];
}

export interface Flow {
  id: FlowId;
  /** What starts it (folded text). */
  triggers: readonly RegExp[];
  steps: Record<string, FlowStep>;
}

export const FLOWS: readonly Flow[] = [
  {
    id: "signin",
    triggers: [
      /\bno (puedo|logro|consigo|me deja) (entrar|ingresar|iniciar|acceder|abrir)\b/,
      /\bno me deja (entrar|ingresar|iniciar)\b/,
      /\b(can t|cannot|can not|unable to) (log|sign) ?in\b/,
      /\b(problemas?|error) (para |al |con )?(entrar|ingresar|iniciar sesion|el acceso)\b/,
    ],
    steps: {
      start: {
        options: [
          { id: "forgot", next: { faq: "cant_sign_in" } },
          { id: "wait", next: { faq: "cant_sign_in" } },
          { id: "code", next: { faq: "two_steps" } },
          { id: "mail", next: { faq: "emails" } },
          { id: "other", next: { person: true } },
        ],
      },
    },
  },
  {
    id: "nopicks",
    triggers: [
      /\bno (veo|me salen|me aparecen|aparecen|hay|salen) (ningun )?(picks?|pronosticos?)\b/,
      /\b(donde|dónde) (estan|están) (los )?picks\b/,
      /\bwhere (are|is) (the |my )?picks?\b/,
      /\b(i )?(can t|cannot|don t) (see|find) (the |any )?picks?\b/,
    ],
    steps: {
      start: {
        options: [
          { id: "none", next: { faq: "no_pick" } },
          { id: "locked", next: { step: "locked" } },
          { id: "empty", next: { person: true } },
        ],
      },
      locked: {
        options: [
          { id: "expired", next: { faq: "membership_ends" } },
          { id: "unsure", next: { faq: "renew" } },
          { id: "active", next: { person: true } },
        ],
      },
    },
  },
  {
    id: "pay",
    triggers: [
      /\b(quiero|necesito|puedo|como|donde) (pagar|renovar|suscribirme|comprar)\b/,
      /\b(how|where) (do i|can i|to) (pay|renew|subscribe)\b/,
      /\bi want to (pay|renew|subscribe)\b/,
      /\b(pagar|pago) (la )?(membresia|suscripcion|plan)\b/,
    ],
    steps: {
      start: {
        options: [
          { id: "renew", next: { faq: "renew" } },
          { id: "trial", next: { faq: "trial" } },
          { id: "ends", next: { faq: "membership_ends" } },
          { id: "other", next: { person: true } },
        ],
      },
    },
  },
];

export function flowOf(query: string): Flow | null {
  const text = plain(query);
  return FLOWS.find((f) => f.triggers.some((r) => r.test(text))) ?? null;
}

export function flowById(id: FlowId): Flow {
  return FLOWS.find((f) => f.id === id)!;
}

/** What is offered when nothing was found: three questions of the help that readers ask most. */
export const SUGGESTED: readonly FaqId[] = ["cant_sign_in", "renew", "no_pick"];
