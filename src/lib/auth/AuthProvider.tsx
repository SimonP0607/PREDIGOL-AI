/**
 * Who is signed in, what they may do, and how they want things shown.
 *
 * The session lives in an HttpOnly cookie the browser never reads: this layer only
 * asks the API who it is (/auth/me). Permissions here decide what is PRESENTED; the
 * API enforces them independently on every request.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { LiveApiError, STAGE_EVENT, UNAUTHENTICATED_EVENT, v1 } from "@/lib/api/v1/client";
import { live } from "@/lib/api/v1/queries";
import type { Language, Me, PermissionKey, PreferencesIn } from "@/lib/api/v1/types_auth";
import { browserLocale, isLocale, rememberLocale, type Locale } from "@/lib/i18n";
import { detectTimeZone, isValidTimeZone } from "@/lib/time";

/** staged: the password was right, but a step of signing in is still owed (user.stage). */
export type AuthStatus = "loading" | "anonymous" | "staged" | "signed-in" | "error";

interface AuthValue {
  status: AuthStatus;
  user: Me | null;
  error: LiveApiError | null;
  /** True after the API said this browser's session ended (not after a plain sign-out). */
  sessionExpired: boolean;
  can: (permission: PermissionKey) => boolean;
  isSuperAdmin: boolean;
  /** SUPER_ADMIN looking at the product as a USER would. Presentation only. */
  previewAsUser: boolean;
  setPreviewAsUser: (on: boolean) => void;
  /** What the screen should show: admin chrome and admin-only controls. */
  showAdmin: boolean;
  /** Admin-only: lay unqualified shadow picks out as the product would (clearly labelled). */
  shadowPreview: boolean;
  setShadowPreview: (on: boolean) => void;
  locale: Locale;
  timeZone: string;
  signIn: (email: string, password: string) => Promise<Me>;
  /** A step of signing in answered with the next Me (a new session): store it. */
  completeStep: (who: Me) => void;
  signOut: () => Promise<void>;
  updatePreferences: (prefs: PreferencesIn) => Promise<Me>;
  setLocale: (locale: Locale) => Promise<void>;
  retry: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);
const PREVIEW_KEY = "predigol.previewAsUser";
const SHADOW_KEY = "predigol.shadowPreview";

function readFlag(key: string): boolean {
  try {
    return window.sessionStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function writeFlag(key: string, on: boolean): void {
  try {
    if (on) window.sessionStorage.setItem(key, "1");
    else window.sessionStorage.removeItem(key);
  } catch {
    /* storage unavailable: the flag lasts for this page only */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const me = useQuery({ ...live.me });
  const [previewAsUser, setPreview] = useState<boolean>(() => readFlag(PREVIEW_KEY));
  const [shadowOn, setShadowOn] = useState<boolean>(() => readFlag(SHADOW_KEY));
  const [sessionExpired, setSessionExpired] = useState(false);
  const [anonLocale, setAnonLocale] = useState<Locale>(browserLocale);

  const error = me.error instanceof LiveApiError ? me.error : null;
  const user = me.data ?? null;
  const status: AuthStatus = me.isPending
    ? "loading"
    : user
      ? user.stage && user.stage !== "full"
        ? "staged"
        : "signed-in"
      : error && error.status !== 401
        ? "error"
        : "anonymous";

  useEffect(() => {
    function onUnauthenticated() {
      setSessionExpired(true);
      queryClient.setQueryData(["auth", "me"], null);
      void queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    }
    function onStage() {
      void queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
    }
    window.addEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
    window.addEventListener(STAGE_EVENT, onStage);
    return () => {
      window.removeEventListener(UNAUTHENTICATED_EVENT, onUnauthenticated);
      window.removeEventListener(STAGE_EVENT, onStage);
    };
  }, [queryClient]);

  const setPreviewAsUser = useCallback((on: boolean) => {
    setPreview(on);
    writeFlag(PREVIEW_KEY, on);
  }, []);

  const setShadowPreview = useCallback((on: boolean) => {
    setShadowOn(on);
    writeFlag(SHADOW_KEY, on);
  }, []);

  const completeStep = useCallback(
    (who: Me) => {
      // A new session (each step issues one): nothing cached under the old one is kept.
      queryClient.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
      queryClient.setQueryData(["auth", "me"], who);
      setSessionExpired(false);
      rememberLocale(who.language);
    },
    [queryClient],
  );

  const signIn = useCallback(
    async (email: string, password: string) => {
      const who = await v1.login(email, password);
      completeStep(who);
      return who;
    },
    [completeStep],
  );

  const signOut = useCallback(async () => {
    try {
      await v1.logout();
    } finally {
      setPreviewAsUser(false);
      setSessionExpired(false);
      queryClient.clear();
      queryClient.setQueryData(["auth", "me"], null);
    }
  }, [queryClient, setPreviewAsUser]);

  const updatePreferences = useCallback(
    async (prefs: PreferencesIn) => {
      const who = await v1.updatePreferences(prefs);
      queryClient.setQueryData(["auth", "me"], who);
      rememberLocale(who.language);
      return who;
    },
    [queryClient],
  );

  const setLocale = useCallback(
    async (locale: Locale) => {
      rememberLocale(locale);
      if (user) {
        await updatePreferences({ language: locale as Language });
      } else {
        setAnonLocale(locale);
      }
    },
    [user, updatePreferences],
  );

  const value = useMemo<AuthValue>(() => {
    const permissions = new Set(user?.permissions ?? []);
    const isSuperAdmin = permissions.has("admin");
    const locale: Locale = user && isLocale(user.language) ? user.language : anonLocale;
    const timeZone = user && isValidTimeZone(user.timezone) ? user.timezone : detectTimeZone();
    return {
      status,
      user,
      error,
      sessionExpired,
      can: (p) => permissions.has(p),
      isSuperAdmin,
      previewAsUser: isSuperAdmin && previewAsUser,
      setPreviewAsUser,
      showAdmin: isSuperAdmin && !previewAsUser,
      shadowPreview:
        isSuperAdmin && !previewAsUser && permissions.has("admin.shadow_preview") && shadowOn,
      setShadowPreview,
      locale,
      timeZone,
      signIn,
      completeStep,
      signOut,
      updatePreferences,
      setLocale,
      retry: () => void me.refetch(),
    };
  }, [
    status,
    user,
    error,
    sessionExpired,
    previewAsUser,
    setPreviewAsUser,
    shadowOn,
    setShadowPreview,
    anonLocale,
    signIn,
    completeStep,
    signOut,
    updatePreferences,
    setLocale,
    me,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/** The `preview` value for product queries: "shadow" only while a SUPER_ADMIN has the shadow preview on. */
export function usePreviewParam(): "shadow" | undefined {
  return useAuth().shadowPreview ? "shadow" : undefined;
}
