/** The sheet's shared pieces (plan UX, A14): the categories in their order, the limit, and the hook any page opens it with. */
import { createContext, useContext } from "react";
import type { SupportCategory } from "@/lib/api/v1/types_support";

/** The order the reader is offered them in (fbi.customer.support.CATEGORIES): the urgent one first. */
export const CATEGORIES: readonly SupportCategory[] = [
  "access",
  "account",
  "technical",
  "wrong_data",
  "suggestion",
  "complaint",
];
/** A reader's message (section 32: «el texto libre tiene un máximo de 2.000 caracteres»). */
export const MAX_TEXT = 2000;
/** Open tickets a reader may have at once (fbi.customer.support.MAX_OPEN). */
export const MAX_OPEN = 3;

export interface ReportOptions {
  category?: SupportCategory | undefined;
  /** The match a «wrong data» report is about. */
  matchId?: number | undefined;
  /** The error the reader is looking at, when the sheet opens from it. */
  requestId?: string | null | undefined;
}

export interface ReportValue {
  /** Whether this account can write to PrediGol now (FBI_SUPPORT on; a reader, or the owner previewing as one). */
  available: boolean;
  open: (options?: ReportOptions) => void;
}

export const ReportContext = createContext<ReportValue>({
  available: false,
  open: () => undefined,
});

/** «Reportar un problema» from anywhere: ``available`` says whether to offer it at all. */
export function useReportProblem(): ReportValue {
  return useContext(ReportContext);
}
