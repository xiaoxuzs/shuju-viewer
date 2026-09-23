import { useId, useRef, useState } from "react";
import { createImportUpload, createUnknownFormatFromUpload, uploadImportFile } from "@/api/client";
import type { UnknownFormatImportOut } from "@/api/types";
import { Button } from "@/components/ui/button";
import { parseApiError } from "@/lib/apiError";

export function ManagedCaseUpload({ dataType, formatName, formatDetails, onCreated }: {
  dataType: string; formatName: string; formatDetails: string | null;
  onCreated: (result: UnknownFormatImportOut) => void;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const selectionId = useId();
  const [files, setFiles] = useState<File[]>([]);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [uploaded, setUploaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [automatic, setAutomatic] = useState(false);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const id = uploadId ?? (await createImportUpload("AGENT_UNKNOWN")).upload_id;
      setUploadId(id);
      if (!uploaded) {
        for (const [index, file] of files.entries()) {
          await uploadImportFile(id, file.webkitRelativePath || file.name, file, () => {}).promise;
          setProgress(index + 1);
        }
        setUploaded(true);
      }
      onCreated(await createUnknownFormatFromUpload({ upload_id: id, data_type: dataType,
        format_name: formatName, format_details: formatDetails, delivery_policy: automatic ? "auto_test" : "manual" }));
    } catch (cause) {
      setError(parseApiError(cause).message ?? "Managed upload or Case handoff failed.");
    } finally { setBusy(false); }
  };
  return <section className="space-y-2 rounded-md border p-3">
    <h3 className="font-semibold">Upload unknown-format source files</h3>
    <p className="text-xs text-muted-foreground">Use this for files on your computer. Viewer pins the completed upload to the Case; no server path is supplied by the browser.</p>
    <input ref={fileInput} type="file" hidden multiple disabled={busy || uploadId !== null} aria-label="Unknown source files"
      onChange={(event) => setFiles(Array.from(event.target.files ?? []))} />
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-input px-3 py-2">
      <Button type="button" variant="outline" size="sm" disabled={busy || uploadId !== null}
        aria-describedby={selectionId} onClick={() => fileInput.current?.click()}>
        Choose files
      </Button>
      <span id={selectionId} role="status" className="text-sm text-muted-foreground">
        {files.length === 0 ? "No files selected" : `${files.length} ${files.length === 1 ? "file" : "files"} selected`}
      </span>
    </div>
    <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={automatic} disabled={busy || uploadId !== null}
      onChange={(event) => setAutomatic(event.target.checked)} />Automatically deliver in an authorized test environment</label>
    <Button disabled={busy || !files.length || (uploadId !== null && !uploaded && error !== null)} onClick={() => void submit()}>
      {busy ? `Uploading / handing off (${progress}/${files.length})` : uploaded ? "Retry Case handoff" : "Upload files and create Case"}
    </Button>
    {error && <p role="alert" className="text-sm text-destructive">{error}{!uploaded && " The incomplete upload is retained; reopen this dialog to start a new upload."}</p>}
  </section>;
}
