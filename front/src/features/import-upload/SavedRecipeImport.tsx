import { useState } from "react";
import { api, pickImportFolder } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TransitionLink } from "@/features/page-transition";
import type { ImportRecipe } from "@/features/agent-import/ImportRecipe";
import type { UnknownFormatImportOut } from "@/api/types";

export function SavedRecipeImport({ recipe }: { recipe: ImportRecipe }) {
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<UnknownFormatImportOut | null>(null);
  async function start() {
    setBusy(true); setError("");
    try {
      const { data } = await api.post<UnknownFormatImportOut>(`/import-recipes/${recipe.recipe_id}/from-path`, { source_path: path, version: recipe.version });
      setResult(data);
    } catch { setError("Unable to start this saved import. Check the source folder and try again."); }
    finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-md border p-3">
    <p>{recipe.name} v{recipe.version}</p>
    <Input aria-label="Saved import source folder" value={path} disabled={busy} onChange={event => { setPath(event.target.value); setResult(null); }} />
    <Button variant="outline" disabled={busy} onClick={() => {
      void pickImportFolder().then(result => { if (result.path) { setPath(result.path); setResult(null); } }).catch(() => setError("Folder selection failed."));
    }}>Choose folder</Button>
    <Button disabled={busy || !path.trim()} onClick={() => void start()}>Start saved import</Button>
    {result?.status === "SUCCESS" && <p role="status">Source already imported. No new import or model task was started.</p>}
    {result && <TransitionLink to={`/agent-import-cases/${result.case_id}`}>{result.status === "SUCCESS" ? "Open existing result" : "Open import progress"}</TransitionLink>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
