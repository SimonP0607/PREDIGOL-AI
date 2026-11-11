import * as React from "react";

import { cn } from "@/lib/utils";
import { fieldVariants, type FieldSize } from "./field";

export interface InputProps extends Omit<React.ComponentProps<"input">, "size"> {
  /** `sm`: the 40 px field of a dense form. */
  fieldSize?: Exclude<FieldSize, "area">;
}

/** A text field of «Noche de partido» (ui/field.ts). */
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, fieldSize, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(fieldVariants({ size: fieldSize }), className)}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
