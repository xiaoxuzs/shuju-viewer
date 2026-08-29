import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, CheckCircle2, Loader2, MessageSquare, OctagonX, RefreshCw } from "lucide-react";
import { useParams } from "react-router-dom";

import type { AgentImportCaseOut } from "@/api/types";
import { PageHeader } from "@/components/common/page-header";
import { PageLoading } from "@/components/common/page-loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  answerAgentImportCase,
  approveAgentImportCase,
  fetchAgentImportArtifacts,
  fetchAgentImportAttempts,
  fetchAgentImportCase,
  fetchAgentImportMessages,
  reworkAgentImportCase,
  stopAgentImportCase,
} from "@/features/agent-import/api";
import { TransitionLink, usePageTransitionReady } from "@/features/page-transition";
import { parseApiError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

const TERMINAL_STATUSES = new Set(["SUCCESS", "FAILED", "STOPPED"]);

function statusVariant(status: string): "default" | "outline" | "secondary" | "success" | "destructive" {
  if (status === "SUCCESS") return "success";
  if (status === "FAILED" || status === "STOPPED") return "destructive";
  if (status === "READY_FOR_REVIEW" || status === "NEEDS_USER") return "default";
  return "secondary";
}

export function AgentImportCasePage() {
  const { caseId = "" } = useParams();
  const queryClient = useQueryClient();
  const [feedback, setFeedback] = useState("");
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const caseQuery = useQuery({
    queryKey: ["agent-import-case", caseId],
    queryFn: () => fetchAgentImportCase(caseId),
    enabled: Boolean(caseId),
    refetchInterval: (query) => {
      const item = query.state.data;
      return item && TERMINAL_STATUSES.has(item.status) ? false : 1_500;
    },
  });
  const detailPollInterval = caseQuery.data && TERMINAL_STATUSES.has(caseQuery.data.status) ? false : 1_500;
  const messagesQuery = useQuery({
    queryKey: ["agent-import-case", caseId, "messages"],
    queryFn: () => fetchAgentImportMessages(caseId),
    enabled: Boolean(caseId),
    refetchInterval: detailPollInterval,
  });
  const attemptsQuery = useQuery({
    queryKey: ["agent-import-case", caseId, "attempts"],
    queryFn: () => fetchAgentImportAttempts(caseId),
    enabled: Boolean(caseId),
    refetchInterval: detailPollInterval,
  });
  const artifactsQuery = useQuery({
    queryKey: ["agent-import-case", caseId, "artifacts"],
    queryFn: () => fetchAgentImportArtifacts(caseId),
    enabled: Boolean(caseId),
    refetchInterval: detailPollInterval,
  });
  usePageTransitionReady(!caseQuery.isLoading);

  const item = caseQuery.data;
  const refreshCase = async (next?: AgentImportCaseOut) => {
    if (next) queryClient.setQueryData(["agent-import-case", caseId], next);
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["agent-import-case", caseId] }),
      queryClient.invalidateQueries({ queryKey: ["agent-import-cases"] }),
    ]);
  };
  const runAction = async (name: string, action: () => Promise<AgentImportCaseOut>) => {
    setBusyAction(name);
    setActionError(null);
    try {
      const next = await action();
      setFeedback("");
      await refreshCase(next);
    } catch (error) {
      const parsed = parseApiError(error);
      setActionError(parsed.message ?? "The Agent action failed.");
    } finally {
      setBusyAction(null);
    }
  };

  if (caseQuery.isLoading) return <PageLoading />;
  if (!item) {
    return (
      <Card><CardContent className="p-6 text-sm text-destructive">Unable to load this Agent import case.</CardContent></Card>
    );
  }

  const canStop = !TERMINAL_STATUSES.has(item.status) && item.status !== "STOPPING";
  const canAnswer = item.status === "NEEDS_USER";
  const canReview = item.status === "READY_FOR_REVIEW";

  return (
    <>
      <PageHeader
        title={item.source_profile}
        description="Unknown-format Agent import: controlled planning, .zp generation, deep validation, then explicit approval."
        crumbs={[
          { label: "Datasets", to: "/datasets" },
          { label: "Agent cases", to: "/agent-import-cases" },
          { label: item.case_id },
        ]}
        actions={
          <>
            <Badge variant={statusVariant(item.status)}>{item.status.replaceAll("_", " ")}</Badge>
            {canStop && (
              <Button variant="outline" size="sm" disabled={busyAction !== null} onClick={() => void runAction("stop", () => stopAgentImportCase(caseId))}>
                <OctagonX className="h-4 w-4" /> Stop
              </Button>
            )}
          </>
        }
      />

      {actionError && (
        <p className="mb-5 rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
          {actionError}
        </p>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(300px,0.6fr)]">
        <div className="space-y-5">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-lg"><Bot className="h-5 w-5 text-primary" /> Case activity</CardTitle>
              <CardDescription>Agent decisions and user guidance, ordered by context revision.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {messagesQuery.data?.map((message) => (
                <div key={message.message_id} className={cn("rounded-md border p-3 text-sm", message.sender_type === "USER" ? "border-primary/30 bg-primary/5" : "border-border/60 bg-muted/20")}>
                  <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline">{message.sender_type.replace("_", " ")}</Badge>
                    <span>{message.message_kind}</span>
                    <span>revision {message.context_revision}</span>
                  </div>
                  <p className="whitespace-pre-wrap break-words">{message.content}</p>
                </div>
              ))}
              {messagesQuery.data?.length === 0 && <p className="text-sm text-muted-foreground">No activity recorded yet.</p>}
            </CardContent>
          </Card>

          {(canAnswer || canReview) && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-lg"><MessageSquare className="h-5 w-5" /> {canAnswer ? "Agent needs input" : "Review .zp candidate"}</CardTitle>
                <CardDescription>{canAnswer ? "Answer the latest question so the Agent can retry with a new context revision." : "Approval imports the validated binary into Viewer; rework returns it to analysis."}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                <textarea
                  rows={4}
                  value={feedback}
                  placeholder={canAnswer ? "Provide the missing format information…" : "Optional review feedback for rework…"}
                  className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  onChange={(event) => setFeedback(event.target.value)}
                />
                <div className="flex flex-wrap justify-end gap-2">
                  {canAnswer && (
                    <Button disabled={!feedback.trim() || busyAction !== null} onClick={() => void runAction("answer", () => answerAgentImportCase(caseId, feedback.trim(), item.version))}>
                      {busyAction === "answer" && <Loader2 className="h-4 w-4 animate-spin" />} Send answer
                    </Button>
                  )}
                  {canReview && (
                    <>
                      <Button variant="outline" disabled={!feedback.trim() || busyAction !== null} onClick={() => void runAction("rework", () => reworkAgentImportCase(caseId, feedback.trim(), item.version))}>
                        {busyAction === "rework" ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Request rework
                      </Button>
                      <Button disabled={busyAction !== null} onClick={() => void runAction("approve", () => approveAgentImportCase(caseId, item.version))}>
                        {busyAction === "approve" ? <Loader2 className="h-4 w-4 animate-spin" /> : <CheckCircle2 className="h-4 w-4" />} Approve and import
                      </Button>
                    </>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {item.status === "SUCCESS" && item.dataset_slug && (
            <Card className="border-[hsl(var(--success)/0.4)]">
              <CardContent className="flex flex-wrap items-center justify-between gap-3 p-5">
                <div><div className="font-semibold">Dataset import complete</div><div className="text-sm text-muted-foreground">The approved .zp is registered in Viewer.</div></div>
                <Button asChild><TransitionLink to={`/datasets/${item.dataset_slug}`}>Open dataset</TransitionLink></Button>
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-5">
          <Card>
            <CardHeader><CardTitle className="text-lg">Case details</CardTitle></CardHeader>
            <CardContent><dl className="space-y-3 text-sm">
              <Detail label="Analysis" value={item.analysis_category.replaceAll("_", " ")} />
              <Detail label="Fingerprint" value={item.dataset_fingerprint} mono />
              <Detail label="Source" value={item.source_ref} mono />
              <Detail label="Mode" value={item.interaction_mode} />
              <Detail label="Attempts" value={`${item.autonomous_attempt_used} autonomous / ${item.guided_attempt_no} guided`} />
              {item.candidate_zp_sha256 && <Detail label="Candidate SHA-256" value={item.candidate_zp_sha256} mono />}
            </dl></CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-lg">Attempts</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {attemptsQuery.data?.map((attempt) => (
                <div key={attempt.attempt_id} className="flex items-center justify-between gap-3 rounded-md border border-border/60 p-2">
                  <span>#{attempt.attempt_no} · revision {attempt.context_revision}</span>
                  <Badge variant={attempt.result === "SUCCESS" ? "success" : attempt.result === "FAILED" ? "destructive" : "outline"}>{attempt.result}</Badge>
                </div>
              ))}
              {attemptsQuery.data?.length === 0 && <p className="text-muted-foreground">No attempts yet.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="text-lg">Binary artifacts</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-sm">
              {artifactsQuery.data?.map((artifact) => (
                <div key={artifact.artifact_id} className="rounded-md border border-border/60 p-2">
                  <div className="font-medium">{artifact.artifact_type}</div>
                  <div className="mt-1 break-all font-mono text-xs text-muted-foreground">{artifact.sha256}</div>
                  <div className="mt-1 text-xs text-muted-foreground">{artifact.size_bytes.toLocaleString()} bytes</div>
                </div>
              ))}
              {artifactsQuery.data?.length === 0 && <p className="text-muted-foreground">No artifacts yet.</p>}
            </CardContent>
          </Card>

          {item.verification && (
            <Card>
              <CardHeader><CardTitle className="text-lg">Deep verification</CardTitle></CardHeader>
              <CardContent><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/40 p-3 text-xs">{JSON.stringify(item.verification, null, 2)}</pre></CardContent>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

function Detail({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return <div><dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt><dd className={cn("mt-0.5 break-all", mono && "font-mono text-xs")}>{value}</dd></div>;
}
