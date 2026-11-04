/**
 * Choosing a password (plan UX, A7; R11 of the security plan): the account's address as the username the system's
 * password manager saves it under, the new password twice, and a meter that says - while the reader types - what the
 * server will say: how long it must be (15 characters, or 12 with a second factor) and what it must not be. Pasting
 * is welcome; there are no composition rules.
 */
import { useId, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { checkPassword } from "@/lib/auth/passwordRule";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { accountInput } from "./AccountShell";

export function NewPassword({
  email,
  name,
  hasMfa,
  value,
  onChange,
  repeat,
  onRepeat,
}: {
  email: string;
  name?: string | undefined;
  hasMfa?: boolean | undefined;
  value: string;
  onChange: (v: string) => void;
  repeat: string;
  onRepeat: (v: string) => void;
}) {
  const id = useId();
  const [show, setShow] = useState(false);
  const check = checkPassword(value, { email, name, hasMfa });
  const mismatch = repeat.length > 0 && repeat !== value;
  const level = check.strength;
  return (
    <div className="space-y-4">
      {/* The address as the username: the password manager saves the new password under the right account. */}
      <label className="block">
        <span className="text-xs font-medium text-muted-foreground">{t("auth.email")}</span>
        <input
          type="email"
          name="username"
          autoComplete="username"
          value={email}
          readOnly
          className={cn(accountInput, "bg-muted/40 text-muted-foreground")}
          data-testid="account-email"
        />
      </label>
      <label className="block" htmlFor={`${id}-new`}>
        <span className="text-xs font-medium text-muted-foreground">
          {t("auth.account.newPassword")}
        </span>
        <span className="relative mt-1 block">
          <input
            id={`${id}-new`}
            type={show ? "text" : "password"}
            name="new-password"
            autoComplete="new-password"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            aria-describedby={`${id}-rule`}
            className={cn(accountInput, "mt-0 pr-12")}
            data-testid="new-password"
          />
          <button
            type="button"
            onClick={() => setShow((v) => !v)}
            aria-label={show ? t("auth.hidePassword") : t("auth.showPassword")}
            className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-muted-foreground hover:text-foreground"
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </span>
      </label>
      <div
        id={`${id}-rule`}
        className="space-y-1.5"
        data-testid="password-meter"
        data-level={level}
      >
        <div className="flex gap-1" aria-hidden>
          {[1, 2, 3, 4].map((n) => (
            <span
              key={n}
              className={cn(
                "h-1.5 flex-1 rounded-full",
                level >= n
                  ? level === 1
                    ? "bg-negative"
                    : level === 2
                      ? "bg-warning"
                      : "bg-positive"
                  : "bg-border",
              )}
            />
          ))}
        </div>
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {level === 0
            ? t("auth.account.rule", { min: check.minLength })
            : t(`auth.account.strength.${level}`)}
        </p>
        {check.problems.length ? (
          <ul
            className="list-disc space-y-0.5 pl-5 text-xs text-negative"
            data-testid="password-problems"
          >
            {check.problems.map((p) => (
              <li key={p}>{t(`errors.problem.${p}`, { min: check.minLength })}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <label className="block">
        <span className="text-xs font-medium text-muted-foreground">
          {t("auth.steps.repeatPassword")}
        </span>
        <input
          type={show ? "text" : "password"}
          name="new-password-repeat"
          autoComplete="new-password"
          value={repeat}
          onChange={(e) => onRepeat(e.target.value)}
          className={accountInput}
          data-testid="new-password-repeat"
        />
      </label>
      {mismatch ? (
        <p role="alert" className="text-xs text-negative">
          {t("auth.steps.passwordMismatch")}
        </p>
      ) : null}
    </div>
  );
}
