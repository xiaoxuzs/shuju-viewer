"""Drive import via the same HTTP path as the frontend; poll job and summarize timings.

Placed under ``viewer/tools/`` so saving the file does not trigger ``uvicorn --reload``
when the dev server watches ``back/``.

Usage::

    e:\\viewer\\back\\.venv\\Scripts\\python.exe e:\\viewer\\tools\\import_job_benchmark.py --source-path \"E:/viewer/shuju/MZ20160222DS_histone48_html\"

Requires: ``curl`` on PATH (Windows 10+), backend reachable at ``--base-url``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_wall() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_json(url: str, timeout: float = 30.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _delete_dataset(base: str, slug: str) -> None:
    url = f"{base.rstrip('/')}/api/v1/datasets/{slug}"
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req, timeout=120.0) as resp:
        resp.read()


def _curl_post_import(base: str, source_path: str, slug: str, name: str) -> tuple[int, str, float]:
    """POST JSON /imports; return (http_code, body, elapsed_seconds)."""
    url = f"{base.rstrip('/')}/api/v1/imports"
    payload = json.dumps({"source_path": source_path, "slug": slug, "name": name}, ensure_ascii=False)
    cmd = [
        "curl",
        "-sS",
        "-m",
        "0",
        "--connect-timeout",
        "30",
        "-w",
        "\n__CURLHTTP__%{http_code}",
        "-X",
        "POST",
        url,
        "-H",
        "Accept: application/json",
        "-H",
        "Content-Type: application/json",
        "--data-binary",
        payload,
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - t0
    out = proc.stdout or ""
    m = re.search(r"\n__CURLHTTP__(\d{3})\s*$", out)
    code = int(m.group(1)) if m else 0
    body = out[: m.start()] if m else out
    if proc.returncode != 0:
        raise RuntimeError(f"curl failed rc={proc.returncode} stderr={proc.stderr!r}")
    return code, body.strip(), elapsed


_DB_STAGES = frozenset({"init", "proteins", "matches", "finalize"})


@dataclass
class Sample:
    wall_iso: str
    rel: float
    payload: dict[str, Any]


@dataclass
class RunLog:
    base_url: str
    source_path: str
    slug: str
    post_http_code: int = 0
    post_elapsed_s: float = 0.0
    post_body: str = ""
    job_id: str | None = None
    samples: list[Sample] = field(default_factory=list)
    error: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "source_path": self.source_path,
            "slug": self.slug,
            "post_http_code": self.post_http_code,
            "post_elapsed_s": self.post_elapsed_s,
            "post_body": self.post_body[:2000],
            "job_id": self.job_id,
            "error": self.error,
            "samples": [
                {"t_wall": s.wall_iso, "since_post_s": s.rel, **s.payload} for s in self.samples
            ],
            "summary": self.summarize(),
        }

    def summarize(self) -> dict[str, Any]:
        if not self.samples:
            return {}
        rows = self.samples
        last = rows[-1]

        fp_start = next((s.rel for s in rows if s.payload.get("stage") == "fingerprint"), None)
        t_fingerprint = None
        if fp_start is not None:
            after = next((s.rel for s in rows if s.payload.get("stage") not in ("fingerprint", None)), None)
            if after is not None:
                t_fingerprint = after - fp_start
            else:
                t_fingerprint = last.rel - fp_start

        last_fp = max((s.rel for s in rows if s.payload.get("stage") == "fingerprint"), default=None)
        first_db = next(
            (s.rel for s in rows if s.payload.get("stage") in _DB_STAGES),
            None,
        )
        after_fp_to_db_s = None
        if last_fp is not None and first_db is not None:
            after_fp_to_db_s = max(0.0, first_db - last_fp)

        ingest_wall_s = None
        if first_db is not None and last.payload.get("status") == "success":
            ingest_wall_s = last.rel - first_db

        return {
            "total_poll_wall_s": last.rel,
            "post_elapsed_s": self.post_elapsed_s,
            "fingerprint_wall_s_est": t_fingerprint,
            "after_fingerprint_to_first_db_stage_s_est": after_fp_to_db_s,
            "first_db_stage_to_success_s_est": ingest_wall_s,
            "final_status": last.payload.get("status"),
            "final_stage": last.payload.get("stage"),
            "final_progress": last.payload.get("progress"),
            "final_stage_detail": last.payload.get("stage_detail"),
        }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8000", help="API origin (no trailing /api)")
    p.add_argument("--source-path", type=str, required=True, help="Server path to dataset folder")
    p.add_argument("--slug", default="", help="Dataset slug (default: auto)")
    p.add_argument("--name", default="", help="Display name (default: auto)")
    p.add_argument("--poll-interval", type=float, default=2.0)
    p.add_argument("--out", type=Path, default=None, help="Write JSON log here")
    args = p.parse_args()

    src = args.source_path.strip()
    if not src:
        print("Empty --source-path", file=sys.stderr)
        return 2

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = args.slug.strip() or f"bench-48-{stamp}"
    name = args.name.strip() or f"Import benchmark {stamp}"

    log = RunLog(base_url=args.base_url, source_path=src, slug=slug)
    repo_root = Path(__file__).resolve().parents[1]
    out_path = args.out or repo_root / "logs" / f"import-benchmark-{slug}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        code, body, elapsed = _curl_post_import(args.base_url, src, slug, name)
    except Exception as exc:
        log.error = f"POST failed: {exc}"
        out_path.write_text(json.dumps(log.to_jsonable(), indent=2), encoding="utf-8")
        print(json.dumps(log.to_jsonable(), indent=2))
        return 1

    log.post_http_code = code
    log.post_elapsed_s = elapsed
    log.post_body = body

    if code == 409:
        try:
            detail = json.loads(body).get("detail")
            if isinstance(detail, dict) and detail.get("slug"):
                conflict_slug = str(detail["slug"])
                print(f"409 conflict; deleting dataset slug={conflict_slug!r} and retrying once…")
                _delete_dataset(args.base_url, conflict_slug)
                code, body, elapsed = _curl_post_import(args.base_url, src, slug, name)
                log.post_http_code = code
                log.post_elapsed_s += elapsed
                log.post_body = body
        except Exception as exc:
            log.error = f"409 handling failed: {exc}"
            out_path.write_text(json.dumps(log.to_jsonable(), indent=2), encoding="utf-8")
            print(json.dumps(log.to_jsonable(), indent=2))
            return 1

    if code != 202:
        log.error = f"Unexpected HTTP {code}: {body[:500]}"
        out_path.write_text(json.dumps(log.to_jsonable(), indent=2), encoding="utf-8")
        print(json.dumps(log.to_jsonable(), indent=2))
        return 1

    try:
        created = json.loads(body)
        log.job_id = str(created["job_id"])
    except Exception as exc:
        log.error = f"Bad JSON from POST: {exc} body={body[:300]!r}"
        out_path.write_text(json.dumps(log.to_jsonable(), indent=2), encoding="utf-8")
        print(json.dumps(log.to_jsonable(), indent=2))
        return 1

    t_post_end = time.perf_counter()

    job_url = f"{args.base_url.rstrip('/')}/api/v1/imports/{log.job_id}"
    last_key: tuple[Any, ...] | None = None
    while True:
        rel = time.perf_counter() - t_post_end
        try:
            payload = _get_json(job_url, timeout=60.0)
        except urllib.error.HTTPError as exc:
            log.error = f"GET job HTTP {exc.code}"
            break
        except Exception as exc:
            log.error = f"GET job failed: {exc}"
            break

        key = (
            payload.get("status"),
            payload.get("stage"),
            payload.get("progress"),
            payload.get("stage_detail"),
            payload.get("updated_at"),
        )
        if key != last_key:
            log.samples.append(Sample(wall_iso=_utc_wall(), rel=rel, payload=dict(payload)))
            last_key = key
            print(
                f"[{rel:8.1f}s] status={payload.get('status')} stage={payload.get('stage')} "
                f"progress={payload.get('progress')} detail={str(payload.get('stage_detail'))[:80]!r}"
            )

        if payload.get("status") in ("success", "failed"):
            break
        time.sleep(max(0.5, float(args.poll_interval)))

    out_path.write_text(json.dumps(log.to_jsonable(), indent=2), encoding="utf-8")
    print(f"\nWrote log: {out_path}")
    print(json.dumps(log.to_jsonable()["summary"], indent=2))
    return 0 if log.samples and log.samples[-1].payload.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
