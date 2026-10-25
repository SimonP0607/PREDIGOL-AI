/**
 * The password rule as the page can check it while the reader types (R11 of the security plan, plan UX A7): the same
 * rule the server applies (backend fbi/auth/passwords.py) - at least 15 characters, or 12 with a second factor, at
 * most 128; not the service's name, the address or the name of the account; not a trivial repetition or run. The
 * server also checks a list of common passwords and has the last word: this only helps, it never decides.
 */

export const MIN_LENGTH = 15;
export const MIN_LENGTH_WITH_MFA = 12;
export const MAX_LENGTH = 128;
const CONTEXT_WORDS = ["predigol"];

export type PasswordProblem =
  | "password_too_short"
  | "password_too_long"
  | "password_edge_whitespace"
  | "password_is_email"
  | "password_has_context"
  | "password_too_simple";

export interface PasswordContext {
  email?: string | undefined;
  name?: string | undefined;
  hasMfa?: boolean | undefined;
}

export interface PasswordCheck {
  problems: PasswordProblem[];
  /** 0 nothing typed, 1 not enough, 2 enough, 3 good, 4 very good. */
  strength: 0 | 1 | 2 | 3 | 4;
  minLength: number;
}

/** Lower case, accents off, letters and digits only: «María-José» -> «mariajose». */
export function folded(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .replace(/[^a-z0-9]/g, "");
}

function contextWords({ email, name }: PasswordContext): string[] {
  const words = [...CONTEXT_WORDS];
  if (email) words.push(folded(email.split("@")[0] ?? ""));
  if (name) words.push(...name.split(/[^\p{L}\p{N}_]+/u).map(folded));
  return words.filter((w) => w.length >= 4);
}

function step(a: string, b: string): number | null {
  if (/\d/.test(a) && /\d/.test(b)) {
    const d = (((Number(b) - Number(a)) % 10) + 10) % 10;
    return d === 1 ? 1 : d === 9 ? -1 : null;
  }
  if (/[a-z]/i.test(a) && /[a-z]/i.test(b)) {
    const d = b.toLowerCase().charCodeAt(0) - a.toLowerCase().charCodeAt(0);
    return d === 1 || d === -1 ? d : null;
  }
  return null;
}

/** Too few different characters, one short unit repeated three times or more, or one run from end to end. */
export function trivial(password: string): boolean {
  const chars = Array.from(password);
  if (new Set(chars).size < 4) return true;
  const n = chars.length;
  for (let unit = 1; unit <= Math.floor(n / 3); unit++) {
    if (chars.every((c, i) => c === chars[i % unit])) return true;
  }
  const steps = new Set<number | null>();
  for (let i = 1; i < n; i++) steps.add(step(chars[i - 1] ?? "", chars[i] ?? ""));
  return n > 2 && steps.size === 1 && !steps.has(null);
}

export function minLength(hasMfa: boolean | undefined): number {
  return hasMfa ? MIN_LENGTH_WITH_MFA : MIN_LENGTH;
}

export function checkPassword(password: string, ctx: PasswordContext = {}): PasswordCheck {
  const min = minLength(ctx.hasMfa);
  const length = Array.from(password).length;
  if (!password) return { problems: [], strength: 0, minLength: min };
  const problems: PasswordProblem[] = [];
  if (length < min) problems.push("password_too_short");
  if (length > MAX_LENGTH) problems.push("password_too_long");
  if (password.trim() !== password) problems.push("password_edge_whitespace");
  const lowered = password.trim().toLowerCase();
  const email = ctx.email?.toLowerCase();
  if (email && (lowered === email || lowered === email.split("@")[0]))
    problems.push("password_is_email");
  else if (contextWords(ctx).some((w) => folded(password).includes(w)))
    problems.push("password_has_context");
  if (trivial(password)) problems.push("password_too_simple");
  let strength: PasswordCheck["strength"] = problems.length ? 1 : 2;
  if (!problems.length) {
    const distinct = new Set(Array.from(password)).size;
    const words = password.split(/[\s\-_.]+/).filter((w) => w.length >= 3).length;
    if (length >= min + 4 || words >= 3) strength = 3;
    if (length >= 20 && distinct >= 10) strength = 4;
  }
  return { problems, strength, minLength: min };
}

/** Whether a new password and its repetition can be sent: the rule the page knows is met and both say the same. */
export function passwordReady(value: string, repeat: string, ctx: PasswordContext = {}): boolean {
  return value.length > 0 && value === repeat && checkPassword(value, ctx).problems.length === 0;
}
