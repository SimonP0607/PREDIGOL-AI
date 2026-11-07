/**
 * What the guide of Perfil says (plan UX-053, section 6): only what exists for this account. The steps about notifications and
 * about membership and help are built from what the API already says is there (the weekly summary, the notices on the device,
 * WhatsApp, the membership), so the guide never names something that is off. Pure: the facts come in, catalog keys go out.
 */
export interface ProfileFacts {
  /** The weekly summary by e-mail can reach this reader (the API lists its purpose). */
  digest: boolean;
  /** The notices on the device are available (PrediGol's key is set). */
  device: boolean;
  /** Ayuda shows a WhatsApp number. */
  whatsapp: boolean;
  /** The account has a membership (the owner's has none). */
  membership: boolean;
  /** Blocks start open (1024 px and up); under it they are folded. */
  desk: boolean;
}

export const PROFILE_STEPS = [
  "account",
  "football",
  "notifications",
  "privacy",
  "security",
  "last",
] as const;
export type ProfileStep = (typeof PROFILE_STEPS)[number];

const K = "guides.profile";

/** The title of a step: the last one is «Membresía y Ayuda», or only «Ayuda» for an account without membership. */
export function profileTitle(step: string, facts: Pick<ProfileFacts, "membership">): string {
  return step === "last" && !facts.membership ? `${K}.last.titleHelp` : `${K}.${step}.title`;
}

/** The catalog keys of the text of a step, in the order they are read. */
export function profileParts(step: string, f: ProfileFacts): string[] {
  const parts: string[] = [];
  switch (step) {
    case "account":
      parts.push(`${K}.account.body`);
      if (!f.desk) parts.push(`${K}.account.tap`);
      break;
    case "football":
      parts.push(`${K}.football.body`, `${K}.football.region`);
      break;
    case "notifications":
      parts.push(`${K}.notifications.body`);
      if (f.digest) parts.push(`${K}.notifications.digest`);
      if (f.device) parts.push(`${K}.notifications.device`);
      break;
    case "last":
      if (f.membership) parts.push(`${K}.last.membership`);
      parts.push(`${K}.last.help`);
      if (f.whatsapp) parts.push(`${K}.last.whatsapp`);
      break;
    default:
      parts.push(`${K}.${step}.body`);
  }
  return parts;
}
