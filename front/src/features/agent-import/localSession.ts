// A launcher handoff is single-use and short-lived, never an operator key.
// Consume/remove the fragment before any application request or navigation.
export async function initializeLocalSession(): Promise<void> {
  const fragment = new URLSearchParams(window.location.hash.slice(1));
  const handoff = fragment.get("viewer-handoff");
  if (!handoff) return;
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
  const response = await fetch("/api/v1/local-session/exchange", {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ handoff }),
  });
  if (!response.ok) throw new Error("Local session expired or was rejected. Open Viewer again with the trusted local launcher.");
  const session = await response.json() as { csrf: string; expires_at: number };
  window.sessionStorage.setItem("viewer.csrf", session.csrf);
  window.sessionStorage.removeItem("viewer.operatorToken");
}
