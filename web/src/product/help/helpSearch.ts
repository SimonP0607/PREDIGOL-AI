/**
 * The help centre's assistant (plan maestro UX/UI 2026, decision 5; sheet H02): a guided search that runs in the reader's
 * browser over the texts the help already has - the 25 answers, the glossary's terms and «Cómo funciona» - and says where
 * each answer comes from. It writes nothing of its own and calls no AI: what it shows is those texts, word for word.
 *
 * It never gives a forecast or betting advice: a question that asks for one gets a fixed text and the way to Picks and to
 * responsible gaming. A question it finds nothing for offers «Hablar con una persona» with what was typed.
 */
import { fold, TERM_KEYS, termAnchor, termName, termShort, GLOSSARY_PATH } from "@/lib/glossary";
import { t } from "@/lib/i18n";
import { FAQ_GROUPS, faqAnchor, faqAnswer, faqQuestion, type FaqId } from "./faq";
import { NO_REACH, type Reach } from "./reach";
import { HOW_CARD_IDS, HOW_PATH, cardAnchor, type HowCardId } from "./howItWorks";

export type AssistantSource = "faq" | "glossary" | "how";

export interface AssistantAnswer {
  source: AssistantSource;
  id: string;
  title: string;
  text: string;
  /** Where it comes from, in the reader's words: «Preguntas frecuentes · Cuenta y acceso». */
  origin: string;
  /** The place of the help that holds it. */
  to: string;
  hash: string;
}

export type AssistantResult =
  | { kind: "empty" }
  | { kind: "blocked" }
  | { kind: "none" }
  | { kind: "found"; answers: AssistantAnswer[] };

/** At most this many answers: the best ones, never a list to scroll. */
export const MAX_ANSWERS = 3;

/**
 * What the assistant never answers (decision 5): who wins, what to bet, a pick on request, a sure bet. Folded text (no
 * accents, lower case), Spanish and English.
 */
const BLOCKED: readonly RegExp[] = [
  /\b(quien|cual) (va a ganar|gana|ganara)\b/,
  /\bque (apuesto|juego|me recomiendas apostar)\b/,
  /\b(a que|a quien|a cual|por quien|por cual) (le )?(apuesto|voy|juego)\b/,
  /\b(dame|damelo|quiero|recomiendame|sugiereme|pasame) (un |el |los |unos )?(pick|picks|pronostico|pronosticos|parlay|fijo|fijos)\b/,
  /\b(apuesta|pick|parlay) segur[ao]\b/,
  /\bfij[oa]s? (de|para) (hoy|manana)\b/,
  /\b(cuanto|cuanta plata|cuanto dinero) (apuesto|debo apostar|le meto)\b/,
  /\b(who|which team) (wins|will win|is going to win)\b/,
  /\bwhat (should|do) i bet\b/,
  /\b(give|send) me (a |the |some )?(pick|picks|tip|tips|parlay)\b/,
  /\bsure (bet|pick|thing)\b/,
  /\bhow much should i (bet|stake)\b/,
];

const STOP = new Set([
  "como",
  "que",
  "cual",
  "para",
  "por",
  "con",
  "sin",
  "los",
  "las",
  "una",
  "uno",
  "unos",
  "del",
  "mis",
  "the",
  "and",
  "how",
  "what",
  "can",
  "does",
  "for",
  "with",
  "you",
  "are",
  "puedo",
  "hago",
  "hacer",
  "esta",
  "este",
  "eso",
  "cuando",
  "donde",
  "porque",
  "why",
  "when",
  "where",
]);

export function assistantWords(query: string): string[] {
  return fold(query)
    .split(/[^a-z0-9ñ]+/)
    .filter((w) => w.length >= 3 && !STOP.has(w));
}

export function isBlocked(query: string): boolean {
  const text = fold(query)
    .replace(/[^a-z0-9ñ ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return BLOCKED.some((r) => r.test(text));
}

/**
 * Words readers use for what the help calls something else (folded). A word matches its own synonyms too: «clave» finds
 * the answer about the contraseña, «plata» the one about payments.
 */
const SYNONYMS: Record<string, readonly string[]> = {
  clave: ["contrasena", "password"],
  contrasena: ["clave", "password"],
  password: ["contrasena", "clave"],
  plata: ["pago", "pagar"],
  dinero: ["pago", "pagar"],
  cobran: ["pago", "pagar"],
  cobrar: ["pago", "pagar"],
  cuesta: ["membresia", "pago"],
  precio: ["membresia", "pago"],
  vale: ["membresia", "pago"],
  suscripcion: ["membresia"],
  subscription: ["membership"],
  ingresar: ["entrar", "acceso"],
  loguear: ["entrar", "acceso"],
  login: ["entrar", "acceso"],
  celular: ["telefono", "movil"],
  movil: ["telefono", "celular"],
  email: ["correo", "correos"],
  mail: ["correo", "correos"],
  mails: ["correos"],
  notificaciones: ["avisos"],
  notificacion: ["avisos"],
  notifications: ["notices", "alerts"],
  borrar: ["eliminar"],
  eliminar: ["borrar"],
  combinada: ["parlay"],
  combinadas: ["parlay"],
  apuesta: ["pick"],
};

/** The words of a text, folded. */
function tokensOf(text: string): string[] {
  return fold(text)
    .split(/[^a-z0-9ñ]+/)
    .filter((w) => w.length > 0);
}

/** Whether two words differ by one letter at most (a typo): one inserted, left out, changed or swapped. */
export function nearly(a: string, b: string): boolean {
  if (a === b) return true;
  const la = a.length;
  const lb = b.length;
  if (Math.abs(la - lb) > 1) return false;
  if (la === lb) {
    let diff = 0;
    let first = -1;
    for (let i = 0; i < la; i++) {
      if (a[i] === b[i]) continue;
      diff += 1;
      if (first < 0) first = i;
      if (diff > 2) return false;
    }
    if (diff === 1) return true;
    // two letters swapped: «membersía»
    return diff === 2 && a[first] === b[first + 1] && a[first + 1] === b[first];
  }
  const [long, short] = la > lb ? [a, b] : [b, a];
  let i = 0;
  while (i < short.length && long[i] === short[i]) i++;
  return long.slice(i + 1) === short.slice(i);
}

/**
 * How well a text of the help answers: 3 for each word of the question in its title, 1 for each in its body. It counts
 * only if a word is in the title or every word is somewhere in it: never a guess from a stray word of the body.
 */
function score(words: string[], title: string, body: string): number {
  const head = fold(title);
  const rest = fold(body);
  const headTokens = tokensOf(title);
  const restTokens = tokensOf(body);
  // a word of five letters or more may have a typo (one letter), and its synonyms count as itself
  const hits = (word: string, text: string, tokens: string[]): boolean => {
    const variants = [word, ...(SYNONYMS[word] ?? [])];
    return variants.some((v) => {
      // the root of a long word, so «renovar» finds «renovación» and «memberships» finds «membership»
      const w = v.length > 5 ? v.slice(0, -2) : v;
      if (text.includes(w)) return true;
      return (
        v.length >= 5 &&
        tokens.some(
          (tok) => nearly(v, tok) || (tok.length > 5 && nearly(v, tok.slice(0, v.length))),
        )
      );
    });
  };
  let total = 0;
  let inTitle = 0;
  let found = 0;
  for (const word of words) {
    if (hits(word, head, headTokens)) {
      total += 3;
      inTitle += 1;
      found += 1;
    } else if (hits(word, rest, restTokens)) {
      total += 1;
      found += 1;
    }
  }
  return inTitle > 0 || found === words.length ? total : 0;
}

function faqGroupOf(id: FaqId): string {
  const group = FAQ_GROUPS.find((g) => (g.items as readonly string[]).includes(id));
  return group ? t(`support.help.groups.${group.id}`) : "";
}

/** Every text the assistant may answer with, as the help shows it now. `faqShown`: the questions on the page (push). */
function candidates(faqShown: readonly FaqId[], reach: Reach): AssistantAnswer[] {
  const faq = faqShown.map((id): AssistantAnswer => {
    return {
      source: "faq",
      id,
      title: faqQuestion(id),
      text: faqAnswer(id, reach),
      origin: `${t("support.assistant.from.faq")} · ${faqGroupOf(id)}`,
      to: "/help",
      hash: faqAnchor(id),
    };
  });
  const glossary = TERM_KEYS.map((key): AssistantAnswer => ({
    source: "glossary",
    id: key,
    title: termName(key),
    text: termShort(key),
    origin: t("support.assistant.from.glossary"),
    to: GLOSSARY_PATH,
    hash: termAnchor(key),
  }));
  const how = HOW_CARD_IDS.map((id: HowCardId): AssistantAnswer => ({
    source: "how",
    id,
    title: t(`support.howItWorks.cards.${id}.title`),
    text: t(`support.howItWorks.cards.${id}.what`),
    origin: t("support.assistant.from.how"),
    to: HOW_PATH,
    hash: cardAnchor(id),
  }));
  return [...faq, ...glossary, ...how];
}

/** One text of the help as an answer, by its source and id (what a button of a flow or of a topic opens). */
export function answerOf(
  source: AssistantSource,
  id: string,
  faqShown: readonly FaqId[],
  reach: Reach = NO_REACH,
): AssistantAnswer | null {
  return candidates(faqShown, reach).find((a) => a.source === source && a.id === id) ?? null;
}

export function ask(
  query: string,
  faqShown: readonly FaqId[],
  reach: Reach = NO_REACH,
): AssistantResult {
  if (query.trim().length === 0) return { kind: "empty" };
  if (isBlocked(query)) return { kind: "blocked" };
  const words = assistantWords(query);
  if (words.length === 0) return { kind: "none" };
  const ranked = candidates(faqShown, reach)
    .map((answer, order) => ({ answer, order, points: score(words, answer.title, answer.text) }))
    .filter((r) => r.points > 0)
    .sort((a, b) => b.points - a.points || a.order - b.order)
    .slice(0, MAX_ANSWERS)
    .map((r) => r.answer);
  return ranked.length > 0 ? { kind: "found", answers: ranked } : { kind: "none" };
}
