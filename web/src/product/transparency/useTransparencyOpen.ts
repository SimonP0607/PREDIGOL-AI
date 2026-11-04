import { useAuth } from "@/lib/auth/AuthProvider";

/** Whether «Cómo le va a PrediGol» is open to this account (readers, once the owner opens it; the owner always). */
export function useTransparencyOpen(): boolean {
  const auth = useAuth();
  return Boolean(auth.user?.transparency) || auth.showAdmin;
}
