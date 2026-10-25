/**
 * Asking before something is removed (plan UX, A1, defect F53): removing a saved pick, a parlay or your own price,
 * and closing the other sessions, happened at the first tap. The trigger opens a dialog that says what goes and that it
 * cannot be undone; only its confirm button acts. Built on the AlertDialog the project already had (Radix: the focus
 * stays inside, Escape and the backdrop cancel). Every button is 44 px tall on a touch screen.
 */
import type { ReactNode } from "react";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { t } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export function ConfirmAction({
  trigger,
  title,
  body,
  confirm,
  onConfirm,
  testId,
}: {
  /** The button that asks: rendered as the dialog's trigger. */
  trigger: ReactNode;
  title: string;
  body: string;
  /** The words of the button that acts ("Quitar", "Borrar"). */
  confirm: string;
  onConfirm: () => void;
  /** confirm-<testId> on the dialog, its confirm and its cancel buttons. */
  testId: string;
}) {
  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
      <AlertDialogContent
        className="w-[calc(100%-2rem)] rounded-xl border-border bg-card"
        data-testid={`confirm-${testId}`}
      >
        <AlertDialogHeader>
          <AlertDialogTitle className="font-display">{title}</AlertDialogTitle>
          <AlertDialogDescription>{body}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter className="gap-2">
          <AlertDialogCancel
            className={cn("mt-0 pointer-coarse:h-11")}
            data-testid={`confirm-${testId}-cancel`}
          >
            {t("common.cancel")}
          </AlertDialogCancel>
          <AlertDialogAction
            onClick={onConfirm}
            className="bg-negative text-white hover:bg-negative/90 pointer-coarse:h-11"
            data-testid={`confirm-${testId}-ok`}
          >
            {confirm}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
