import { cn } from "@/lib/utils";

export type SelectedEvidenceSourceMode =
  | "follow-pfmb-slot"
  | "locked-ms2-scan"
  | "live-ms2"
  | "unknown";

export type SelectedEvidenceBarProps = {
  identificationRt?: number | null;
  selectedMs2Rt?: number | null;
  liveScan?: number | null;
  pfmbSlotIndex?: number | null;
  pfmbSlotRt?: number | null;
  isPfmbApex?: boolean;
  sourceMode: SelectedEvidenceSourceMode;
  matchedIonCount?: number | null;
  className?: string;
};

export function SelectedEvidenceBar({
  identificationRt,
  selectedMs2Rt,
  liveScan,
  pfmbSlotIndex,
  pfmbSlotRt,
  isPfmbApex = false,
  sourceMode,
  matchedIonCount,
  className,
}: SelectedEvidenceBarProps) {
  return (
    <div
      className={cn(
        "sticky top-0 z-20 rounded-md border border-border/80 bg-background/95 px-3 py-2 shadow-sm backdrop-blur",
        className,
      )}
      data-testid="selected-evidence-bar"
    >
      <div className="grid gap-2 text-xs sm:grid-cols-2 xl:grid-cols-5">
        <EvidenceValue
          testId="selected-evidence-identification-rt"
          label="Identification RT"
          value={formatRt(identificationRt)}
        />
        <EvidenceValue
          testId="selected-evidence-selected-rt"
          label="Selected MS2 RT"
          value={formatRt(selectedMs2Rt)}
        />
        <EvidenceValue
          testId="selected-evidence-live-scan"
          label="Live MS2 scan"
          value={formatScan(liveScan)}
          detail={matchedIonCount == null ? undefined : `${matchedIonCount} matched b/y`}
        />
        <EvidenceValue
          testId="selected-evidence-pfmb-slot"
          label="Fragment Match slot"
          value={formatPfmbSlot(pfmbSlotIndex, pfmbSlotRt, isPfmbApex)}
        />
        <EvidenceValue
          testId="selected-evidence-source"
          label="MS2 source"
          value={sourceModeLabel(sourceMode)}
        />
      </div>
    </div>
  );
}

function EvidenceValue({
  testId,
  label,
  value,
  detail,
}: {
  testId: string;
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="min-w-0" data-testid={testId}>
      <div className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="truncate font-medium text-foreground">{value}</div>
      {detail && <div className="truncate text-[11px] text-muted-foreground">{detail}</div>}
    </div>
  );
}

function formatRt(value: number | null | undefined): string {
  return Number.isFinite(value) ? `${value!.toFixed(4)} min` : "N/A";
}

function formatScan(value: number | null | undefined): string {
  return Number.isFinite(value) && value! > 0 ? `#${value}` : "N/A";
}

function formatPfmbSlot(
  slotIndex: number | null | undefined,
  slotRt: number | null | undefined,
  isApex: boolean,
): string {
  if (!Number.isFinite(slotIndex)) return "N/A";
  const rt = Number.isFinite(slotRt) ? ` @ ${slotRt!.toFixed(2)} min` : "";
  return `${slotIndex}${isApex ? " / apex" : ""}${rt}`;
}

function sourceModeLabel(mode: SelectedEvidenceSourceMode): string {
  if (mode === "follow-pfmb-slot") return "Follow Fragment Match slot";
  if (mode === "locked-ms2-scan") return "Locked MS2 scan";
  if (mode === "live-ms2") return "Live XIC selection";
  return "Default match RT";
}
