import { PlotStatus } from "@/components/common/plot-status";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { SpectraScanIndexItem } from "@/features/spectra-only/types";
import { cn, formatNumber } from "@/lib/utils";

export function AcquisitionContextPanel({
  selectedScan,
  parentMs1Scan,
  childMs2Scans,
  onSelectScan,
}: {
  selectedScan: SpectraScanIndexItem | null;
  parentMs1Scan: SpectraScanIndexItem | null;
  childMs2Scans: SpectraScanIndexItem[];
  onSelectScan: (scanNumber: number) => void;
}) {
  const selectedMs2Scan = selectedScan?.ms_level === 2 ? selectedScan : null;
  const contextMs1Scan = selectedScan?.ms_level === 1 ? selectedScan : parentMs1Scan;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Acquisition Context</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {!selectedScan ? (
          <PlotStatus
            kind="empty"
            title="Select a scan to view its acquisition context."
            className="min-h-32"
          />
        ) : selectedScan.ms_level !== 1 && selectedScan.ms_level !== 2 ? (
          <PlotStatus
            kind="empty"
            title="Acquisition context is available for MS1 and MS2 scans."
            className="min-h-32"
          />
        ) : selectedMs2Scan && !parentMs1Scan ? (
          <PlotStatus
            kind="not_found"
            title="Parent MS1 scan was not found for this MS2 scan."
            className="min-h-32"
          />
        ) : contextMs1Scan ? (
          <>
            {selectedMs2Scan ? (
              <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                <Field label="Parent MS1 scan" value={String(contextMs1Scan.scan_number)} />
                <Field label="Parent MS1 RT" value={`${formatNumber(contextMs1Scan.retention_time, 3)} min`} />
                <Field label="Selected MS2 scan" value={String(selectedMs2Scan.scan_number)} />
                <Field label="Selected MS2 RT" value={`${formatNumber(selectedMs2Scan.retention_time, 3)} min`} />
                <Field
                  label="RT delta"
                  value={`${formatNumber(selectedMs2Scan.retention_time - contextMs1Scan.retention_time, 4)} min`}
                />
                <Field label="Precursor m/z" value={formatOptionalNumber(selectedMs2Scan.precursor_mz, 4)} />
                <Field label="Isolation window" value={formatIsolationWindow(selectedMs2Scan)} />
                <Field label="Sibling MS2 scans" value={childMs2Scans.length.toLocaleString()} />
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
                <Field label="MS1 scan" value={String(contextMs1Scan.scan_number)} />
                <Field label="MS1 RT" value={`${formatNumber(contextMs1Scan.retention_time, 3)} min`} />
                <Field label="Child MS2 scans" value={childMs2Scans.length.toLocaleString()} />
                <Field label="TIC" value={formatOptionalNumber(contextMs1Scan.tic, 2)} />
              </div>
            )}
            <ChildMs2List
              scans={childMs2Scans}
              activeScanNumber={selectedMs2Scan?.scan_number ?? null}
              onSelectScan={onSelectScan}
            />
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ChildMs2List({
  scans,
  activeScanNumber,
  onSelectScan,
}: {
  scans: SpectraScanIndexItem[];
  activeScanNumber: number | null;
  onSelectScan: (scanNumber: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">Child MS2 scans</div>
      {scans.length === 0 ? (
        <PlotStatus
          kind="empty"
          title="No child MS2 scans were triggered from this MS1 scan."
          className="min-h-24"
        />
      ) : (
        <div className="max-h-56 overflow-auto rounded-md border border-border/60">
          <table className="w-full text-left text-xs">
            <thead className="sticky top-0 bg-background text-muted-foreground">
              <tr>
                <th className="px-2 py-2 font-medium">Scan</th>
                <th className="px-2 py-2 font-medium">RT min</th>
                <th className="px-2 py-2 font-medium">Precursor m/z</th>
                <th className="px-2 py-2 font-medium">TIC</th>
                <th className="px-2 py-2 font-medium">Isolation window</th>
              </tr>
            </thead>
            <tbody>
              {scans.map((scan) => (
                <tr
                  key={scan.scan_number}
                  className={cn(
                    "cursor-pointer border-t border-border/50 transition-colors hover:bg-accent/50",
                    scan.scan_number === activeScanNumber && "bg-primary/10 text-primary",
                  )}
                  tabIndex={0}
                  onClick={() => onSelectScan(scan.scan_number)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelectScan(scan.scan_number);
                    }
                  }}
                >
                  <td className="px-2 py-1.5 font-mono">{scan.scan_number}</td>
                  <td className="px-2 py-1.5">{formatNumber(scan.retention_time, 3)}</td>
                  <td className="px-2 py-1.5">{formatOptionalNumber(scan.precursor_mz, 4)}</td>
                  <td className="px-2 py-1.5">{formatOptionalNumber(scan.tic, 2)}</td>
                  <td className="px-2 py-1.5">{formatIsolationWindow(scan)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-md border border-border/60 bg-muted/30 p-2">
      <div className="uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-1 truncate font-medium text-foreground">{value}</div>
    </div>
  );
}

function formatOptionalNumber(value: number | null | undefined, digits: number): string {
  return isFiniteNumber(value) ? formatNumber(value, digits) : "-";
}

function formatIsolationWindow(scan: SpectraScanIndexItem): string {
  if (isFiniteNumber(scan.isolation_lower_mz) && isFiniteNumber(scan.isolation_upper_mz)) {
    return `${formatNumber(scan.isolation_lower_mz, 4)}-${formatNumber(scan.isolation_upper_mz, 4)} m/z`;
  }
  if (isFiniteNumber(scan.isolation_target_mz)) {
    return `Target ${formatNumber(scan.isolation_target_mz, 4)} m/z`;
  }
  return "-";
}

function isFiniteNumber(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
