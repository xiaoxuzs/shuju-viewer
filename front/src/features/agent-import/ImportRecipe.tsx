import { useEffect, useState } from "react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export type ImportRecipe = {
  recipe_id: string; name: string; version: number; parent_case_id: string;
  analysis_category: string; display_category: string;
};

export function SaveImportRecipe({ caseId, defaultName, maintenanceTaskId }: {
  caseId: string; defaultName: string; maintenanceTaskId?: string;
}) {
  const [name, setName] = useState(defaultName);
  const [recipes, setRecipes] = useState<ImportRecipe[]>([]);
  const [selected, setSelected] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { void api.get<ImportRecipe[]>("/import-recipes").then(r => setRecipes(r.data)).catch(() => setRecipes([])); }, []);
  async function save() {
    setBusy(true);
    try {
      const prior = recipes.find(item => item.recipe_id === selected);
      const { data } = await api.post<ImportRecipe>(`/agent-import-cases/${caseId}/import-recipe`, {
        name, recipe_id: prior?.recipe_id ?? null, expected_version: prior?.version ?? null,
        maintenance_task_id: maintenanceTaskId ?? null,
      });
      setRecipes(items => [...items.filter(item => item.recipe_id !== data.recipe_id), data]);
      setSelected(data.recipe_id);
      setMessage(`${data.name} v${data.version} is available in ${data.display_category} default imports.`);
    } catch { setMessage("The import format could not be saved. Refresh and try again."); }
    finally { setBusy(false); }
  }
  return <section className="space-y-2 rounded-md border p-3">
    <h3 className="font-semibold">Save to default imports</h3>
    <Input aria-label="Default import format name" value={name} onChange={event => setName(event.target.value)} />
    <select aria-label="Default import to update" className="w-full rounded border p-2" value={selected}
      onChange={event => setSelected(event.target.value)}>
      <option value="">Create a new import format</option>
      {recipes.map(item => <option key={item.recipe_id} value={item.recipe_id}>{item.name} v{item.version}</option>)}
    </select>
    <Button disabled={busy || !name.trim()} onClick={() => void save()}>{selected ? "Update default import" : "Save default import"}</Button>
    {message && <p role="status">{message}</p>}
  </section>;
}
