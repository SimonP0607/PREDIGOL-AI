/**
 * The price chip of «Noche de partido» (the system's sheet 4, plan maestro UX/UI 2026, PR-12): one recipe for every
 * decimal price the product shows - a read-only pill, a parlay toggle, an in-play price. Archivo, tabular figures,
 * three heights. It draws the price it is given; it never computes one.
 */
import { cva, type VariantProps } from "class-variance-authority";

export const priceVariants = cva(
  "numeric inline-flex shrink-0 items-center justify-center gap-1.5 border font-extrabold leading-none tabular-nums transition-colors",
  {
    variants: {
      size: {
        /** 32 px: a row of a list, a table's cell. */
        sm: "h-8 min-w-[3.25rem] rounded-chip px-2 text-sm",
        /** 40 px: a card's price. */
        md: "h-10 min-w-16 rounded-[0.625rem] px-3 text-[1.0625rem]",
        /** 52 px: the price of a pick. */
        lg: "h-[3.25rem] min-w-[5.25rem] rounded-field px-3 text-2xl",
      },
      tone: {
        plain: "border-border-strong bg-elevated text-foreground",
        /** PrediGol's own choice: the recommended value. */
        gold: "border-gold/55 bg-gold/8 text-gold-strong",
        /** The best price of a comparison. */
        best: "border-primary/55 bg-elevated text-primary",
        /** In «Mi parlay». */
        chosen: "border-gold bg-gold text-gold-foreground",
        /** In play and suspended: shown, locked. */
        locked: "border-warning/40 bg-warning-soft text-warning",
        /** Withdrawn for now: words, not a price. */
        none: "border-dashed border-border-strong bg-transparent font-medium text-subtle-foreground",
      },
    },
    defaultVariants: { size: "md", tone: "plain" },
  },
);

export type PriceSize = NonNullable<VariantProps<typeof priceVariants>["size"]>;
export type PriceTone = NonNullable<VariantProps<typeof priceVariants>["tone"]>;
