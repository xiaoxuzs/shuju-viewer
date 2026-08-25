import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, X } from "lucide-react";

import { createAgentZpImport } from "@/api/client";
import type {
  AgentZpAnalysisCategory,
  AgentZpBinaryOperation,
  AgentZpImportOut,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { TransitionLink } from "@/features/page-transition";
import { parseApiError } from "@/lib/apiError";
import { cn } from "@/lib/utils";

interface AgentZpImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const OPERATIONS: Array<{ value: AgentZpBinaryOperation; label: string; help: string }> = [
  { value: "register_existing_zp", label: "Register .zp", help: "Use an existing validated .zp file" },
  { value: "convert_supported_binary_to_zp", label: "Convert source", help: "Run the configured ZP worker first" },
];

const CATEGORIES: Array<{ value: AgentZpAnalysisCategory; label: string }> = [
  { value: "SPECTRA_ONLY", label: "Spectra" },
  { value: "TOP_DOWN", label: "Top-Down" },
  { value: "BOTTOM_UP", label: "Bottom-Up" },
];

export function AgentZpImportDialog({ open, onOpenChange }: AgentZpImportDialogProps) {
  const queryClient = useQueryClient();
  const [binaryOperation, setBinaryOperation] = useState<AgentZpBinaryOperation>("register_existing_zp");
  const [analysisCategory, setAnalysisCategory] = useState<AgentZpAnalysisCategory>("SPECTRA_ONLY");
  const [sourcePath, setSourcePath] = useState("");
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [sourceProfile, setSourceProfile] = useState("agent_zp_candidate");
  const [description, setDescription] = useState("");
  const [replaceExisting, setReplaceExisting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AgentZpImportOut | null>(null);

  const canSubmit = sourcePath.trim() && slug.trim() && name.trim() && sourceProfile.trim() && !busy;

  async function submit() {
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const created = await createAgentZpImport({
        source_path: sourcePath.trim(),
        slug: slug.trim(),
        name: name.trim(),
        description: description.trim() || null,
        analysis_category: analysisCategory,
        source_profile: sourceProfile.trim(),
        binary_operation: binaryOperation,
        format_version: null,
        replace_existing: replaceExisting,
      });
      setResult(created);
      await queryClient.invalidateQueries({ queryKey: ["datasets"] });
    } catch (err) {
      const parsed = parseApiError(err);
      if (parsed.status === 403 || parsed.status === 404) {
        setError("Agent-ZP import is disabled. Enable ZP_MANAGEMENT_ENABLED=true and ZP_IMPORT_CONVERSION_ENABLED=true on the backend.");
      } else {
        setError(parsed.message ?? "Agent-ZP import failed.");
      }
    } finally {
      setBusy(false);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay/65 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="agent-zp-dialog-title"
    >
      <Card className="max-h-[94vh] w-full max-w-2xl overflow-y-auto border-border/80 shadow-xl">
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <div>
              <CardTitle id="agent-zp-dialog-title">Agent-ZP import</CardTitle>
              <CardDescription className="mt-1.5">
                Create a Viewer dataset from a structured Agent binary plan.
              </CardDescription>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label="Close Agent-ZP import dialog"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-5">
          <section className="space-y-2" aria-labelledby="agent-zp-operation-title">
            <h3 id="agent-zp-operation-title" className="text-sm font-semibold">1. Binary operation</h3>
            <div className="grid grid-cols-2 gap-2" role="radiogroup" aria-label="Binary operation">
              {OPERATIONS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={binaryOperation === option.value}
                  title={option.help}
                  disabled={busy}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm font-medium transition-colors",
                    binaryOperation === option.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-background hover:bg-muted",
                    "disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-foreground",
                  )}
                  onClick={() => setBinaryOperation(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </section>

          <section className="space-y-2" aria-labelledby="agent-zp-category-title">
            <h3 id="agent-zp-category-title" className="text-sm font-semibold">2. Category</h3>
            <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Analysis category">
              {CATEGORIES.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  role="radio"
                  aria-checked={analysisCategory === option.value}
                  disabled={busy}
                  className={cn(
                    "rounded-md border px-3 py-2 text-sm font-medium transition-colors",
                    analysisCategory === option.value
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-background hover:bg-muted",
                    "disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-foreground",
                  )}
                  onClick={() => setAnalysisCategory(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </section>

          <section className="grid gap-3 sm:grid-cols-2" aria-labelledby="agent-zp-fields-title">
            <h3 id="agent-zp-fields-title" className="text-sm font-semibold sm:col-span-2">3. Import fields</h3>
            <div className="space-y-1.5 sm:col-span-2">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="agent-zp-source-path">
                Source path
              </label>
              <Input
                id="agent-zp-source-path"
                value={sourcePath}
                disabled={busy}
                placeholder={binaryOperation === "register_existing_zp" ? "E:\\data\\candidate.zp" : "E:\\data\\source-folder"}
                onChange={(event) => setSourcePath(event.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="agent-zp-slug">Slug</label>
              <Input id="agent-zp-slug" value={slug} disabled={busy} onChange={(event) => setSlug(event.target.value)} />
            </div>
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="agent-zp-name">Display name</label>
              <Input id="agent-zp-name" value={name} disabled={busy} onChange={(event) => setName(event.target.value)} />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="agent-zp-source-profile">
                Source profile
              </label>
              <Input
                id="agent-zp-source-profile"
                value={sourceProfile}
                disabled={busy}
                onChange={(event) => setSourceProfile(event.target.value)}
              />
            </div>
            <div className="space-y-1.5 sm:col-span-2">
              <label className="text-xs font-medium text-muted-foreground" htmlFor="agent-zp-description">
                Description
              </label>
              <textarea
                id="agent-zp-description"
                rows={2}
                value={description}
                disabled={busy}
                onChange={(event) => setDescription(event.target.value)}
                className={cn(
                  "flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                  "disabled:cursor-not-allowed disabled:border-border disabled:bg-disabled disabled:text-disabled-foreground",
                )}
              />
            </div>
            <label className="flex items-center gap-2 text-sm sm:col-span-2">
              <input
                type="checkbox"
                checked={replaceExisting}
                disabled={busy}
                onChange={(event) => setReplaceExisting(event.target.checked)}
              />
              Replace existing dataset with the same slug
            </label>
          </section>

          {error && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm text-destructive" role="alert">
              {error}
            </div>
          )}

          {result && (
            <div className="space-y-3 rounded-md border border-primary/30 bg-primary/5 p-3 text-sm">
              <div className="flex items-center gap-2 font-semibold text-primary">
                <CheckCircle2 className="h-4 w-4" />
                ZP verification passed
              </div>
              <div className="grid gap-2 text-xs sm:grid-cols-3">
                <Metric label="Runs" value={result.verification.readable_run_count.toLocaleString()} />
                <Metric label="Scans" value={result.verification.scan_index_total.toLocaleString()} />
                <Metric label="Format" value={`v${result.zp_format_version}`} />
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline">{result.binary_operation}</Badge>
                <Badge variant="secondary">{result.source_profile}</Badge>
              </div>
            </div>
          )}

          <div className="flex flex-wrap justify-end gap-2 pt-1">
            {result?.dataset_slug && (
              <Button asChild size="sm">
                <TransitionLink to={`/datasets/${result.dataset_slug}`}>Open dataset</TransitionLink>
              </Button>
            )}
            <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button type="button" size="sm" disabled={!canSubmit} onClick={() => void submit()}>
              {busy && <Loader2 className="h-4 w-4 animate-spin" />}
              Run Agent-ZP import
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border/60 bg-background p-2">
      <div className="text-[10px] uppercase tracking-wider text-muted-foreground">{label}</div>
      <div className="mt-0.5 truncate font-medium tabular-nums">{value}</div>
    </div>
  );
}
