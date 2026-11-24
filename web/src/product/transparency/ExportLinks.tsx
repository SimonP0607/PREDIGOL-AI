/**
 * The download of the published picks (plan PM, PM-14-08, FBI_TRANSPARENCY_EXPORT): under the list, three plain links - the picks as
 * CSV (the list's own rows, in its order), the calibration with its 95 % interval as CSV, and both as JSON. Nothing is drawn while
 * the switch is off, and no ROI or total of units is offered: the file is what the page shows, to be checked by whoever wants to.
 */
import { Download } from "lucide-react";
import { transparencyExportUrl } from "@/lib/api/v1/client";
import { useTransparencyExportOn } from "@/lib/auth/AuthProvider";
import { t } from "@/lib/i18n";
import { Note } from "./parts";

const KINDS = ["picks", "calibration", "json"] as const;

export function ExportLinksView({ preview }: { preview?: "shadow" | undefined }) {
  return (
    <div className="space-y-2" data-testid="transparency-export">
      <p className="text-sm font-medium">{t("transparency.export.title")}</p>
      <ul className="flex flex-wrap gap-2">
        {KINDS.map((kind) => (
          <li key={kind}>
            <a
              href={transparencyExportUrl(kind, preview)}
              download
              data-testid={`transparency-export-${kind}`}
              className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border-strong px-3 py-2 text-sm font-medium hover:bg-elevated"
            >
              <Download aria-hidden className="h-4 w-4" />
              {t(`transparency.export.${kind}`)}
            </a>
          </li>
        ))}
      </ul>
      <Note>{t("transparency.export.note")}</Note>
    </div>
  );
}

/** The links, or nothing while the account has the download off. */
export function ExportLinks({ preview }: { preview?: "shadow" | undefined }) {
  const on = useTransparencyExportOn();
  return on || preview ? <ExportLinksView preview={preview} /> : null;
}
