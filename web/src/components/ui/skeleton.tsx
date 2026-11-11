import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-lg bg-linear-to-r from-elevated via-popover to-elevated",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
