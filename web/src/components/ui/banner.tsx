import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import {
  CircleAlert,
  CircleCheck,
  Crown,
  Info,
  TriangleAlert,
  X,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * The banner of «Noche de partido» (plan maestro UX/UI 2026, wave 2; the system's sheet 5): a band that stays on the
 * page until what it says is over - information, something that went well, something to attend to, an error - or what
 * belongs to the membership. The colour never says it alone: each tone has its icon, and the words carry the message.
 * An error is announced at once (role="alert"); the others are part of the page unless a `role` says otherwise.
 */
const banner = cva(
  "flex items-start gap-2.5 rounded-control border px-3.5 py-3 text-sm leading-[1.4] text-foreground",
  {
    variants: {
      tone: {
        info: "border-info/30 bg-info/[0.09]",
        success: "border-primary/30 bg-primary/[0.08]",
        warning: "border-warning/35 bg-warning/[0.09]",
        danger: "border-negative/35 bg-negative/[0.09]",
        gold: "border-gold/40 bg-gold-soft",
        neutral: "border-border bg-card",
      },
    },
    defaultVariants: { tone: "info" },
  },
);

export type BannerTone = NonNullable<VariantProps<typeof banner>["tone"]>;

const SIGN: Record<BannerTone, { icon: LucideIcon; colour: string }> = {
  info: { icon: Info, colour: "text-info" },
  success: { icon: CircleCheck, colour: "text-primary" },
  warning: { icon: TriangleAlert, colour: "text-warning" },
  danger: { icon: CircleAlert, colour: "text-negative" },
  gold: { icon: Crown, colour: "text-gold" },
  neutral: { icon: Info, colour: "text-muted-foreground" },
};

export interface BannerProps extends Omit<React.HTMLAttributes<HTMLDivElement>, "title"> {
  tone?: BannerTone;
  /** Another icon than the tone's own, or `false` for none. */
  icon?: LucideIcon | false;
  /** A link or a small button at the end of the band: «Cómo renovar», «Reintentar». */
  action?: React.ReactNode;
  /** With it the band can be closed: its «×», named by `dismissLabel`. */
  onDismiss?: (() => void) | undefined;
  dismissLabel?: string | undefined;
}

export function Banner({
  tone = "info",
  icon,
  action,
  onDismiss,
  dismissLabel,
  className,
  children,
  role,
  ...props
}: BannerProps) {
  const sign = SIGN[tone];
  const Icon = icon === false ? null : (icon ?? sign.icon);
  return (
    <div
      role={role ?? (tone === "danger" ? "alert" : undefined)}
      data-tone={tone}
      className={cn(banner({ tone }), className)}
      {...props}
    >
      {Icon ? (
        <Icon aria-hidden className={cn("mt-px h-[1.125rem] w-[1.125rem] shrink-0", sign.colour)} />
      ) : null}
      <div className="min-w-0 flex-1 break-words">{children}</div>
      {action ? (
        <div className="shrink-0 text-small font-semibold text-primary">{action}</div>
      ) : null}
      {onDismiss ? (
        <button
          type="button"
          onClick={onDismiss}
          aria-label={dismissLabel}
          className="tap relative -my-0.5 flex h-6 w-6 shrink-0 cursor-pointer items-center justify-center rounded-chip text-muted-foreground hover:bg-foreground/[0.07] hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
        >
          <X aria-hidden className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
