import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { LoaderCircle } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The button of «Noche de partido» (plan maestro UX/UI 2026, wave 2; the system's sheet 3). Five kinds by what
 * they do, four heights, and the same answers everywhere: a ring on keyboard focus, a slight press, one way of being
 * disabled and one of being busy.
 *
 *   primary    the one action of a screen or a card (green)
 *   secondary  every other action
 *   text       an action inside a sentence or a row, no box
 *   gold       what belongs to the membership or to PrediGol's recommendation
 *   danger     what cannot be undone
 *
 * `default`, `outline`, `destructive`, `ghost` and `link` are the names the older pieces still use; they draw the
 * same five. On a touch screen the two small heights still answer at 44 px (tap-y).
 */
const buttonVariants = cva(
  "motion-press relative inline-flex shrink-0 cursor-pointer select-none items-center justify-center gap-2 whitespace-nowrap font-display font-bold focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-primary active:scale-[0.98] disabled:pointer-events-none disabled:border-transparent disabled:bg-elevated disabled:bg-none disabled:text-subtle-foreground disabled:shadow-none aria-busy:pointer-events-none [&_svg]:pointer-events-none [&_svg]:size-[1.125rem] [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-linear-to-b from-primary-strong to-primary text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.45),0_14px_28px_-16px_var(--color-primary)] hover:brightness-110 active:brightness-95",
        secondary:
          "border border-border-strong bg-elevated text-foreground hover:bg-popover active:bg-card",
        text: "px-2 text-primary hover:bg-primary-soft",
        gold: "border border-gold/55 bg-gold-soft text-gold-strong hover:bg-gold/20",
        danger: "border border-negative/40 bg-negative/10 text-negative hover:bg-negative/15",
        default:
          "bg-linear-to-b from-primary-strong to-primary text-primary-foreground shadow-[inset_0_1px_0_rgb(255_255_255/0.45),0_14px_28px_-16px_var(--color-primary)] hover:brightness-110 active:brightness-95",
        outline:
          "border border-border-strong bg-elevated text-foreground hover:bg-popover active:bg-card",
        destructive: "border border-negative/40 bg-negative/10 text-negative hover:bg-negative/15",
        ghost: "text-foreground hover:bg-accent",
        link: "px-0 text-primary underline-offset-4 hover:underline",
      },
      size: {
        lg: "h-13 rounded-control px-5 text-base",
        default: "h-12 rounded-control px-5 text-[0.9375rem]",
        sm: "tap-y h-10 rounded-field px-3.5 text-sm",
        xs: "tap-y h-8 rounded-[0.625rem] px-3 text-[0.8125rem] [&_svg]:size-4",
        icon: "h-11 w-11 rounded-field",
      },
      block: { true: "w-full", false: "" },
    },
    defaultVariants: {
      variant: "primary",
      size: "default",
      block: false,
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  /** Busy: the action was taken and its answer has not come. The button keeps its words, turns a wheel and takes no more presses. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, block, asChild = false, loading = false, children, ...props },
    ref,
  ) => {
    const classes = cn(buttonVariants({ variant, size, block, className }));
    if (asChild) {
      return (
        <Slot className={classes} ref={ref} {...props}>
          {children}
        </Slot>
      );
    }
    return (
      <button
        type="button"
        className={classes}
        ref={ref}
        {...props}
        aria-busy={loading || undefined}
        disabled={props.disabled || loading}
      >
        {loading ? <LoaderCircle aria-hidden className="animate-spin" /> : null}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";

export { Button, buttonVariants };
