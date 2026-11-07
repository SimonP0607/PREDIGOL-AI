/**
 * The text of a step of the guide of Perfil (plan UX-053): built from what exists for this account (see profileText.ts). Its
 * own component because it reads the account's facts with hooks, which the card must not do for the other guides.
 */
import { useAuth } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { profileParts, profileTitle } from "./profileText";
import { useProfileFacts } from "./useProfileFacts";

export function ProfileTitle({ step }: { step: string }) {
  const user = useAuth().user;
  return <>{t(profileTitle(step, { membership: Boolean(user?.membership) }))}</>;
}

export function ProfileBody({ step }: { step: string }) {
  const facts = useProfileFacts();
  return (
    <>
      {profileParts(step, facts).map((key) => (
        <p key={key}>{t(key)}</p>
      ))}
    </>
  );
}
