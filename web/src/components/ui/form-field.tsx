import * as React from "react";
import { CircleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * A field with its label, its help and its error («Noche de partido», the system's sheet 3): the label above, one line of
 * help below, and when the value is wrong the error takes the help's place, in words and with an icon - never by
 * colour alone. It wires what a screen reader needs: the label names the control, the help or the error describes it
 * (`aria-describedby`), and an error marks it `aria-invalid`.
 *
 *   <Field label="Correo" hint="Te escribimos solo por tu cuenta." error={problem}>
 *     {(control) => <input type="email" className={fieldVariants()} {...control} />}
 *   </Field>
 */
export interface FieldControl {
  id: string;
  "aria-describedby": string | undefined;
  "aria-invalid": true | undefined;
}

export function Field({
  label,
  hint,
  error,
  id,
  className,
  children,
}: {
  label: React.ReactNode;
  hint?: React.ReactNode;
  /** What is wrong with the value, in the reader's language; nothing when it is fine. */
  error?: React.ReactNode;
  /** The control's id, when the page needs to know it; one is made otherwise. */
  id?: string | undefined;
  className?: string | undefined;
  children: (control: FieldControl) => React.ReactNode;
}) {
  const made = React.useId();
  const control = id ?? made;
  const wrong = error !== undefined && error !== null && error !== false && error !== "";
  const note = wrong ? `${control}-error` : hint ? `${control}-hint` : undefined;
  return (
    <div className={cn("flex min-w-0 flex-col gap-1.5", className)}>
      <FieldLabel htmlFor={control}>{label}</FieldLabel>
      {children({
        id: control,
        "aria-describedby": note,
        "aria-invalid": wrong ? true : undefined,
      })}
      {wrong ? (
        <FieldError id={`${control}-error`}>{error}</FieldError>
      ) : hint ? (
        <FieldHint id={`${control}-hint`}>{hint}</FieldHint>
      ) : null}
    </div>
  );
}

export function FieldLabel({ className, ...props }: React.ComponentProps<"label">) {
  return (
    <label
      className={cn("text-small font-semibold leading-[1.3] text-foreground-soft", className)}
      {...props}
    />
  );
}

export function FieldHint({ className, ...props }: React.ComponentProps<"p">) {
  return <p className={cn("text-xs leading-[1.45] text-muted-foreground", className)} {...props} />;
}

export function FieldError({ className, children, ...props }: React.ComponentProps<"p">) {
  return (
    <p
      role="alert"
      className={cn("flex items-start gap-1.5 text-xs leading-[1.45] text-negative", className)}
      {...props}
    >
      <CircleAlert aria-hidden className="mt-px h-3.5 w-3.5 shrink-0" />
      <span className="min-w-0 break-words">{children}</span>
    </p>
  );
}
