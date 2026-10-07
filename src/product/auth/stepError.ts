/** The message for a refused step of signing in (wrong code, attempts left, wait time, password rules). */
import { LiveApiError } from "@/lib/api/v1/client";
import { t, translateOr } from "@/lib/i18n";

export function stepError(error: unknown): string {
  if (error instanceof LiveApiError) {
    if (error.status === 0) return t("errors.unreachable");
    if (error.code === "too_many_attempts") {
      return t("errors.code.too_many_attempts", { seconds: error.retryAfter ?? 60 });
    }
    if (error.code === "invalid_code" && error.attemptsLeft !== null) {
      return t("auth.steps.invalidCodeLeft", { left: error.attemptsLeft });
    }
    const base = translateOr(`errors.code.${error.code}`, t("errors.generic"));
    const problems = error.problems.map((p) => translateOr(`errors.problem.${p}`, p));
    return [base, ...problems].join(" ");
  }
  return t("errors.generic");
}
