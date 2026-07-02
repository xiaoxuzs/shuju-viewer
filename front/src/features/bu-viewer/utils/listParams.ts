import type { SetURLSearchParams } from "react-router-dom";

export function setListParam(
  searchParams: URLSearchParams,
  setSearchParams: SetURLSearchParams,
  key: string,
  value: string,
  resetPage = true,
) {
  const next = new URLSearchParams(searchParams);
  const trimmed = value.trim();
  if (trimmed) next.set(key, trimmed);
  else next.delete(key);
  if (resetPage) next.set("page", "1");
  setSearchParams(next);
}

export function clearListParams(
  searchParams: URLSearchParams,
  setSearchParams: SetURLSearchParams,
  keys: string[],
) {
  const next = new URLSearchParams(searchParams);
  keys.forEach((key) => next.delete(key));
  next.set("page", "1");
  setSearchParams(next);
}

export function numberParam(value: string | null): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}
