import * as React from "react";

import { cn } from "@/lib/utils";
import { fieldVariants } from "./field";

/** A text area of «Noche de partido» (ui/field.ts). */
const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(
  ({ className, ...props }, ref) => {
    return (
      <textarea className={cn(fieldVariants({ size: "area" }), className)} ref={ref} {...props} />
    );
  },
);
Textarea.displayName = "Textarea";

export { Textarea };
