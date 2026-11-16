/** The switches that shape the bars, from GET /auth/me (plan maestro unificado, UX-152). */
import { useAuth } from "@/lib/auth/AuthProvider";
import type { NavFlags } from "./nav";

export function useNavFlags(): NavFlags {
  const user = useAuth().user;
  return {
    v2: user?.nav_v2 === true,
    news: user?.news_feed === true,
    profiles: user?.profiles === true,
  };
}
