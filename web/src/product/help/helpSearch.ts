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
 * How well a text of the help answers: 3 for each word of the question in its title, 1 for each in its body. It counts
 * only if a word is in the title or every word is somewhere in it: never a guess from a stray word of the body.
 */
function score(words: string[], title: string, body: string): number {
  const head = fold(title);
  const rest = fold(body);
  let total = 0;
  let inTitle = 0;
  let found = 0;
  for (const word of words) {
    // the root of a long word, so «renovar» finds «renovación» and «memberships» finds «membership»
    const w = word.length > 5 ? word.slice(0, -2) : word;
    if (head.includes(w)) {
      total += 3;
      inTitle += 1;
      found += 1;
    } else if (rest.includes(w)) {
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
function candidates(faqShown: readonly FaqId[]): AssistantAnswer[] {
  const faq = faqShown.map((id): AssistantAnswer => {
    return {
      source: "faq",
      id,
      title: faqQuestion(id),
      text: faqAnswer(id),
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

export function ask(query: string, faqShown: readonly FaqId[]): AssistantResult {
  if (query.trim().length === 0) return { kind: "empty" };
  if (isBlocked(query)) return { kind: "blocked" };
  const words = assistantWords(query);
  if (words.length === 0) return { kind: "none" };
  const ranked = candidates(faqShown)
    .map((answer, order) => ({ answer, order, points: score(words, answer.title, answer.text) }))
    .filter((r) => r.points > 0)
    .sort((a, b) => b.points - a.points || a.order - b.order)
    .slice(0, MAX_ANSWERS)
    .map((r) => r.answer);
  return ranked.length > 0 ? { kind: "found", answers: ranked } : { kind: "none" };
}
