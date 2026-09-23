import { useRef, useState } from "react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";

export function PublishedFeedback({ caseId }: { caseId: string }) {
  const [feedback, setFeedback] = useState("");
  const [result, setResult] = useState("");
  const [busy, setBusy] = useState(false);
  const key = useRef(crypto.randomUUID());
  async function submit() {
    setBusy(true);
    try {
      const response = await api.post(`/agent-import-cases/${caseId}/maintenance`, {
        feedback, idempotency_key: key.current, page: window.location.pathname + window.location.search, selection: {},
      });
      setResult(`Maintenance task ${response.data.task_id}: ${response.data.state}. The original delivery is unchanged.`);
    } catch {
      setResult("Feedback could not be registered. No repair or publication was claimed.");
    } finally { setBusy(false); }
  }
  return <section className="space-y-2 rounded-md border p-3">
    <h3 className="font-semibold">Report a problem with this delivery</h3>
    <p className="text-sm text-muted-foreground">The source and published context stay attached. Maintenance does not reopen the initial implementation role.</p>
    <textarea aria-label="Published delivery feedback" className="w-full rounded border p-2" maxLength={4000}
      value={feedback} disabled={busy} onChange={event => { setFeedback(event.target.value); key.current = crypto.randomUUID(); }} />
    <Button disabled={busy || !feedback.trim()} onClick={() => void submit()}>Send delivery feedback</Button>
    {result && <p role="status">{result}</p>}
  </section>;
}
