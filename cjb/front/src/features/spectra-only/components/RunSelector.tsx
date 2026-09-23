import type { DatasetRunSummary } from "@/api/types";

export function RunSelector({
  runs,
  selectedRunId,
  onChange,
}: {
  runs: DatasetRunSummary[];
  selectedRunId: number | null;
  onChange: (runId: number) => void;
}) {
  if (runs.length === 0) return null;
  return (
    <label className="flex items-center gap-2 text-xs text-muted-foreground">
      Run
      <select
        value={selectedRunId ?? ""}
        onChange={(event) => onChange(Number(event.target.value))}
        className="max-w-[420px] rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground"
      >
        {runs.map((run) => (
          <option key={run.run_id} value={run.run_id}>
            {run.raw_format ?? "unknown"} - {run.run_name}
          </option>
        ))}
      </select>
    </label>
  );
}
