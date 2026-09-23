import { api } from "@/api/client";
import type {
  AgentImportArtifactOut,
  AgentImportAttemptOut,
  AgentImportCaseOut,
  AgentImportMessageOut,
} from "@/api/types";

function mutationHeaders(version: number, includeIdempotency = false): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "If-Match": `"${version}"`,
  };
  if (includeIdempotency) {
    headers["Idempotency-Key"] = typeof crypto.randomUUID === "function"
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }
  return headers;
}

export async function fetchAgentImportCases(): Promise<AgentImportCaseOut[]> {
  const { data } = await api.get<AgentImportCaseOut[]>("/agent-import-cases");
  return data;
}

export async function fetchAgentImportCase(caseId: string): Promise<AgentImportCaseOut> {
  const { data } = await api.get<AgentImportCaseOut>(`/agent-import-cases/${caseId}`);
  return data;
}

export async function fetchAgentImportMessages(caseId: string): Promise<AgentImportMessageOut[]> {
  const { data } = await api.get<AgentImportMessageOut[]>(`/agent-import-cases/${caseId}/messages`);
  return data;
}

export async function fetchAgentImportAttempts(caseId: string): Promise<AgentImportAttemptOut[]> {
  const { data } = await api.get<AgentImportAttemptOut[]>(`/agent-import-cases/${caseId}/attempts`);
  return data;
}

export async function fetchAgentImportArtifacts(caseId: string): Promise<AgentImportArtifactOut[]> {
  const { data } = await api.get<AgentImportArtifactOut[]>(`/agent-import-cases/${caseId}/artifacts`);
  return data;
}

export async function answerAgentImportCase(
  caseId: string,
  content: string,
  version: number,
): Promise<AgentImportCaseOut> {
  const { data } = await api.post<AgentImportCaseOut>(
    `/agent-import-cases/${caseId}/messages`,
    { content },
    { headers: mutationHeaders(version, true) },
  );
  return data;
}

export async function approveAgentImportCase(caseId: string, version: number): Promise<AgentImportCaseOut> {
  const { data } = await api.post<AgentImportCaseOut>(
    `/agent-import-cases/${caseId}/review/approve`,
    {},
    { timeout: 600_000, headers: mutationHeaders(version) },
  );
  return data;
}

export async function reworkAgentImportCase(
  caseId: string,
  feedback: string,
  version: number,
): Promise<AgentImportCaseOut> {
  const { data } = await api.post<AgentImportCaseOut>(
    `/agent-import-cases/${caseId}/review/rework`,
    { feedback },
    { headers: mutationHeaders(version) },
  );
  return data;
}

export async function stopAgentImportCase(caseId: string): Promise<AgentImportCaseOut> {
  const { data } = await api.post<AgentImportCaseOut>(`/agent-import-cases/${caseId}/stop`);
  return data;
}
