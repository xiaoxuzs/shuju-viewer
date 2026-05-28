"""Invoke pfmb_bridge.exe (ingest / run / egress) and parse single-line JSON logs."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class PfmbRunnerError(RuntimeError):
    """Raised when pfmb_bridge exits non-zero or returns ok=false."""


@dataclass(frozen=True)
class PfmbRunner:
    exe: Path
    cwd: Path | None = None

    def _parse_bridge_json(self, merged: str) -> dict:
        for line in reversed(merged.strip().splitlines()):
            text = line.strip()
            if text.startswith("{") and text.endswith("}"):
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    return payload
        raise PfmbRunnerError(f"pfmb_bridge did not emit a parseable JSON line.\n{merged[-2000:]}")

    def run(self, args: list[str], *, step: str) -> dict:
        if not self.exe.is_file():
            raise PfmbRunnerError(f"PFMB bridge executable not found: {self.exe}")
        cmd = [str(self.exe), *args]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(self.cwd) if self.cwd else None,
        )
        merged = (proc.stdout or "") + (proc.stderr or "")
        if proc.returncode != 0:
            raise PfmbRunnerError(
                f"pfmb_bridge {step} failed with exit code {proc.returncode}.\n{merged[-4000:]}"
            )
        payload = self._parse_bridge_json(merged)
        if not payload.get("ok"):
            raise PfmbRunnerError(f"pfmb_bridge {step} returned ok=false: {payload}")
        return payload

    def ingest_xml_msalign(
        self,
        *,
        prsm_xml: Path,
        ms2_msalign: Path,
        cache_path: Path,
        manifest_path: Path,
    ) -> int:
        payload = self.run(
            [
                "ingest",
                "--source",
                "xml_msalign",
                "--prsm-xml",
                str(prsm_xml.resolve()),
                "--ms2-msalign",
                str(ms2_msalign.resolve()),
                "--cache",
                str(cache_path.resolve()),
                "--manifest",
                str(manifest_path.resolve()),
            ],
            step="ingest",
        )
        records = int(payload.get("records") or 0)
        if records <= 0:
            raise PfmbRunnerError(f"pfmb_bridge ingest wrote zero records: {payload}")
        if not cache_path.is_file():
            raise PfmbRunnerError(f"pfmb_bridge ingest did not create cache: {cache_path}")
        return records

    def run_engine(
        self,
        *,
        cache_path: Path,
        output_dir: Path,
        preset: str = "native_coverage",
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        payload = self.run(
            [
                "run",
                "--cache",
                str(cache_path.resolve()),
                "--output",
                str(output_dir.resolve()),
                "--preset",
                preset,
                "--rebuild-frag-cache",
            ],
            step="run",
        )
        pfmb_path = output_dir / "results.pfmb"
        if payload.get("pfmb"):
            candidate = Path(str(payload["pfmb"]))
            if candidate.is_file():
                pfmb_path = candidate
        if not pfmb_path.is_file():
            raise PfmbRunnerError(f"pfmb_bridge run did not create results.pfmb under {output_dir}")
        magic = pfmb_path.read_bytes()[:4]
        if magic != b"PFMB":
            raise PfmbRunnerError(f"results.pfmb has unexpected magic {magic!r}")
        return pfmb_path

    def egress_all(
        self,
        *,
        cache_path: Path,
        pfmb_path: Path,
        out_dir: Path,
    ) -> dict:
        out_dir.mkdir(parents=True, exist_ok=True)
        return self.run(
            [
                "egress",
                "--cache",
                str(cache_path.resolve()),
                "--pfmb",
                str(pfmb_path.resolve()),
                "--all",
                "--format",
                "json",
                "--out-dir",
                str(out_dir.resolve()),
            ],
            step="egress",
        )
