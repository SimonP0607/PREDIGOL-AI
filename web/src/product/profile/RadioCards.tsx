/**
 * Choices as cards (sheet U03; UX-150): the system's radio (`ui/radio-group`) inside a card that says what the choice does,
 * with an example at its side. The whole card answers the finger; the radio carries the role, the state and the test id
 * (`<testId>-<value>`), as the segments did.
 */
import { useId, type ReactNode } from "react";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";

export interface RadioCard<T extends string> {
  value: T;
  title: ReactNode;
  body?: ReactNode;
  aside?: ReactNode;
  lang?: string;
}

export function RadioCards<T extends string>({
  value,
  options,
  onChange,
  label,
  testId,
  disabled = false,
}: {
  value: T;
  options: readonly RadioCard<T>[];
  onChange: (value: T) => void;
  label: string;
  testId: string;
  disabled?: boolean;
}) {
  const base = useId();
  return (
    <RadioGroup
      value={value}
      onValueChange={(v) => onChange(v as T)}
      aria-label={label}
      data-testid={testId}
      disabled={disabled}
      className="gap-2"
    >
      {options.map((o) => {
        const id = `${base}-${o.value}`;
        const on = o.value === value;
        return (
          <label
            key={o.value}
            htmlFor={id}
            lang={o.lang}
            className={cn(
              "flex min-h-14 cursor-pointer items-center gap-3 rounded-card border px-4 py-3 transition-colors",
              on
                ? "border-primary/70 bg-primary-soft/40"
                : "border-border bg-card hover:bg-elevated",
            )}
          >
            <RadioGroupItem id={id} value={o.value} data-testid={`${testId}-${o.value}`} />
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold">{o.title}</span>
              {o.body ? (
                <span className="block text-caption text-muted-foreground">{o.body}</span>
              ) : null}
            </span>
            {o.aside ? (
              <span className="numeric shrink-0 text-sm font-semibold">{o.aside}</span>
            ) : null}
          </label>
        );
      })}
    </RadioGroup>
  );
}
