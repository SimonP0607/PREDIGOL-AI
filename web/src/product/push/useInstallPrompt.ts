/** Whether the browser offered its own install prompt (lib/pwa.ts keeps it for the reader's tap, plan UX, B7). */
import { useEffect, useState } from "react";
import { canPromptInstall, onInstallPromptChange } from "@/lib/pwa";

export function useInstallPrompt(): boolean {
  const [can, setCan] = useState(canPromptInstall);
  useEffect(() => onInstallPromptChange(() => setCan(canPromptInstall())), []);
  return can;
}
