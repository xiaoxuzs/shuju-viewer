/**
 * Helpers for mapping a native directory-picker selection to a server-side path string.
 * Standard browsers do not expose absolute paths; some desktop hosts (e.g. Electron) add `File.path`.
 */

export type FileWithNativePath = File & { path?: string };

/** Longest path prefix shared by all paths, normalized to a parent directory (no trailing partial segment). */
export function commonParentDirectory(paths: string[]): string | null {
  if (paths.length === 0) return null;
  const norm = paths.map((p) => p.replace(/\\/g, "/"));
  let prefix = norm[0]!;
  for (let i = 1; i < norm.length; i++) {
    const b = norm[i]!;
    let j = 0;
    while (j < prefix.length && j < b.length && prefix[j] === b[j]) j++;
    prefix = prefix.slice(0, j);
  }
  if (!prefix) return null;
  const lastSep = prefix.lastIndexOf("/");
  if (lastSep < 0) return prefix;
  return prefix.slice(0, lastSep);
}

export function inferServerPathFromDirectoryFileList(files: FileList): string | null {
  const list = Array.from(files) as FileWithNativePath[];
  if (list.length === 0) return null;
  const paths = list.map((f) => f.path).filter((p): p is string => typeof p === "string" && p.length > 0);
  if (paths.length !== list.length) return null;
  const raw = commonParentDirectory(paths);
  if (!raw) return null;
  return normalizePathSeparators(raw, paths[0]!);
}

/** Last path segment (folder or file name) for display / default slug when an absolute path is known. */
export function basenamePath(p: string): string {
  const u = p.replace(/\\/g, "/").replace(/\/+$/, "");
  const i = u.lastIndexOf("/");
  return i >= 0 ? u.slice(i + 1) : u;
}

/** Prefer native separators from the first absolute path sample. */
export function normalizePathSeparators(unixStyle: string, sampleRawPath: string): string {
  const u = unixStyle.replace(/\\/g, "/");
  if (sampleRawPath.includes("\\")) return u.replace(/\//g, "\\");
  return u;
}

/** Default slug from a folder name (URL-friendly; supports non-Latin letters via Unicode categories). */
export function slugifyFolderName(name: string): string {
  const trimmed = name.trim().toLowerCase();
  const collapsed = trimmed
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^\p{L}\p{N}._-]+/gu, "_")
    .replace(/_+/g, "_");
  const s = collapsed.replace(/^_|_$/g, "");
  return s || "dataset";
}
