import { cva, type VariantProps } from "class-variance-authority";

/**
 * The field of «Noche de partido» (plan maestro UX/UI 2026, wave 2; the system's sheet 3): one recipe for every text
 * field, text area and select. 48 px tall, 16 px text (a phone does not zoom in on a field it can focus), the field's
 * own border (3.5 : 1 on the page) over the deep background, a green edge and a soft ring on focus, and red when
 * `aria-invalid` says the value is wrong. `sm` is the 40 px field of a dense form (44 px under a finger).
 *
 *   <input className={fieldVariants()} />
 *   <textarea className={fieldVariants({ size: "area" })} />
 *   <select className={cn(fieldVariants({ size: "sm" }), "mt-1")} />
 */
export const fieldVariants = cva(
  "motion-press w-full min-w-0 border border-input bg-background-deep text-foreground placeholder:text-subtle-foreground focus:border-primary focus:outline-none focus-visible:ring-[3px] focus-visible:ring-primary/25 disabled:cursor-not-allowed disabled:opacity-60 aria-invalid:border-negative aria-invalid:focus-visible:ring-negative/20 [&[readonly]]:border-border-strong [&[readonly]]:bg-elevated [&[readonly]]:text-foreground-soft",
  {
    variants: {
      size: {
        default: "h-12 rounded-field px-3.5 text-base",
        sm: "h-10 rounded-[0.625rem] px-3 text-base sm:text-sm pointer-coarse:h-11",
        area: "min-h-[6.5rem] rounded-field px-3.5 py-3 text-base leading-normal",
      },
    },
    defaultVariants: { size: "default" },
  },
);

export type FieldSize = NonNullable<VariantProps<typeof fieldVariants>["size"]>;
