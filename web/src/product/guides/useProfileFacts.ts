/**
 * The facts the guide of Perfil reads from the account to build its words (plan UX-053; see profileText.ts).
 */
import { useQuery } from "@tanstack/react-query";
import { live } from "@/lib/api/v1/queries";
import { v1 } from "@/lib/api/v1/client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { useI18n } from "@/lib/i18n";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { digestOf } from "@/product/profile/consents";
import { usePush } from "@/product/push/usePush";
import type { ProfileFacts } from "./profileText";

export function useProfileFacts(): ProfileFacts {
  const { locale } = useI18n();
  const user = useAuth().user;
  const account = useQuery({ ...live.account, enabled: Boolean(user) });
  const consents = useQuery({
    queryKey: ["me", "consents", locale],
    queryFn: () => v1.myConsents(locale),
    enabled: Boolean(user),
  });
  const push = usePush();
  const desk = useMediaQuery("(min-width: 1024px)");
  return {
    digest: Boolean(digestOf(consents.data)),
    device: push.available,
    whatsapp: account.data?.help.whatsapp === true,
    membership: Boolean(user?.membership),
    desk,
  };
}
