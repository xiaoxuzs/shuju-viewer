import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, releaseDatasetRevision } from "@/api/client";
import { Button } from "@/components/ui/button";
import { TransitionLink } from "@/features/page-transition";
import { SaveImportRecipe } from "./ImportRecipe";

type MaintenanceTask = { task_id: string; state: string; wait_reason?: string; published_revision_id?: string };
type RevisionHistory = { active_revision_id: string; revisions: Array<{ revision_id: string; state: string }> };
const FINISHED = new Set(["PUBLISHED", "FAILED", "NEEDS_USER", "ENGINEERING_BLOCKED", "AWAITING_REVISION_VALIDATION", "RECONCILIATION_REQUIRED"]);

export function PublishedFeedback({ caseId, datasetSlug }: { caseId: string; datasetSlug?: string }) {
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const [task, setTask] = useState<MaintenanceTask | null>(null);
  const [history, setHistory] = useState<RevisionHistory | null>(null);
  const key = useRef(crypto.randomUUID());
  useEffect(() => {
    void api.get<MaintenanceTask[]>(`/agent-import-cases/${caseId}/maintenance`).then(r => {
      if (r.data.length) setTask(r.data[r.data.length - 1]);
    }).catch(() => setResult("Unable to load previous repair progress."));
  }, [caseId]);
  useEffect(() => {
    void api.get<RevisionHistory>(`/agent-import-cases/${caseId}/revisions`).then(r => setHistory(r.data)).catch(() => setHistory(null));
  }, [caseId, task?.state]);
  useEffect(() => {
    if (!task || FINISHED.has(task.state)) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void api.get<MaintenanceTask[]>(`/agent-import-cases/${caseId}/maintenance`).then(response => {
        const updated = response.data.find(item => item.task_id === task.task_id);
        if (!cancelled && updated) setTask(updated);
      }).catch(() => { if (!cancelled) setResult("Unable to refresh repair progress. The task may still be running."); });
    }, 2000);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [caseId, task?.task_id, task?.state]);
  useEffect(() => {
    if (task?.state === "PUBLISHED" && datasetSlug) {
      releaseDatasetRevision(datasetSlug);
      void queryClient.invalidateQueries({ predicate: query => query.queryKey[0] === "datasets" || query.queryKey.includes(datasetSlug) });
    }
  }, [task?.state, datasetSlug, queryClient]);
  async function submit() {
    setBusy(true);
    try {
      const response = await api.post<MaintenanceTask>(`/agent-import-cases/${caseId}/maintenance`, {
        feedback, idempotency_key: key.current, page: window.location.pathname + window.location.search, selection: {},
      });
      setTask(response.data);
      setResult("Feedback received. Preparing and checking the repair.");
    } catch {
      setResult("Feedback could not be registered. Please try again.");
    } finally { setBusy(false); }
  }
  async function rollback(revisionId: string) {
    if (!history) return;
    setBusy(true);
    try {
      const { data } = await api.post<RevisionHistory>(`/agent-import-cases/${caseId}/revisions/rollback`, {
        revision_id: revisionId, expected_base: history.active_revision_id,
      });
      setHistory(data);
      if (datasetSlug) releaseDatasetRevision(datasetSlug);
      await queryClient.invalidateQueries({ predicate: query => query.queryKey[0] === "datasets" || (!!datasetSlug && query.queryKey.includes(datasetSlug)) });
      setResult("Previous dataset version restored.");
    } catch { setResult("Unable to restore this version. Refresh the current dataset version and try again."); }
    finally { setBusy(false); }
  }
  return <section className="space-y-2 rounded-md border p-3">
    <h3 className="font-semibold">Report a problem with this delivery</h3>
    <p className="text-sm text-muted-foreground">Describe what needs improving. The repair uses the saved source and is applied after validation.</p>
    <textarea aria-label="Published delivery feedback" className="w-full rounded border p-2" maxLength={4000}
      value={feedback} disabled={busy} onChange={event => { setFeedback(event.target.value); key.current = crypto.randomUUID(); }} />
    <Button disabled={busy || !feedback.trim() || (!!task && !FINISHED.has(task.state))} onClick={() => void submit()}>Send delivery feedback</Button>
    {result && <p role="status">{result}</p>}
    {task && <p role="status">{task.state === "PUBLISHED" ? "Repair validated and applied." : `Repair: ${task.state}${task.wait_reason ? ` (${task.wait_reason})` : ""}`}</p>}
    {task?.state === "PUBLISHED" && <>
      {datasetSlug && <TransitionLink to={`/datasets/${datasetSlug}`}>Open repaired dataset</TransitionLink>}
      <SaveImportRecipe caseId={caseId} defaultName="" maintenanceTaskId={task.task_id} />
    </>}
    {history?.revisions.filter(item => item.revision_id !== history.active_revision_id).map(item => (
      <Button key={item.revision_id} variant="outline" disabled={busy} onClick={() => void rollback(item.revision_id)}>
        Restore version {item.revision_id.slice(0, 8)}
      </Button>
    ))}
  </section>;
}
