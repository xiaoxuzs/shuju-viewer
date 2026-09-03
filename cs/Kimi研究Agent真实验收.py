#!/usr/bin/env python3
"""Run the real Agent 1 research loop against the single-sample fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "back"
sys.path.insert(0, str(BACKEND_ROOT))

from app.agent_import.kimi_research_runtime import KimiHttpError, KimiResearchRuntime  # noqa: E402
from app.agent_import.source_sampling import summarize_source_root  # noqa: E402
from app.agent_import.zp_capabilities import build_zp_capabilities  # noqa: E402
from app.core.config import settings  # noqa: E402


DEFAULT_SOURCE = (
    REPO_ROOT.parent
    / "viewer-agent"
    / "maxquant"
    / "maxquant-viz-data"
    / "single-sample"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _base_urls(configured: str) -> tuple[str, ...]:
    primary = configured.rstrip("/")
    if primary == "https://api.moonshot.ai/v1":
        return primary, "https://api.moonshot.cn/v1"
    if primary == "https://api.moonshot.cn/v1":
        return primary, "https://api.moonshot.ai/v1"
    return (primary,)


def main() -> None:
    args = _arguments()
    source = args.source.expanduser().resolve(strict=True)
    key = (settings.moonshot_api_key or "").strip()
    if not key:
        raise SystemExit("MOONSHOT_API_KEY is not configured")
    output = args.output.expanduser().resolve(strict=False) if args.output else None
    trace_output = output.with_suffix(".trace.jsonl") if output else None
    if trace_output:
        trace_output.parent.mkdir(parents=True, exist_ok=True)
        trace_output.unlink(missing_ok=True)

    def record_trace(entry) -> None:
        line = json.dumps(
            {"round": entry.round_no, "tool": entry.tool_name, "status": entry.status},
            ensure_ascii=False,
        )
        print(line, flush=True)
        if trace_output:
            with trace_output.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(entry.model_dump(mode="json"), ensure_ascii=False) + "\n")

    result = None
    last_error = None
    for base_url in _base_urls(settings.moonshot_base_url):
        try:
            result = KimiResearchRuntime(
                base_url=base_url,
                api_key=key,
                model=settings.agent_read_model,
                timeout=settings.moonshot_request_timeout_seconds,
            ).run(
                source_root=str(source),
                case_id="live-agent1-single-sample",
                analysis_category="BOTTOM_UP",
                requested_source_profile="unknown scientific dataset",
                format_details=(
                    "Independently inspect all available spectra, tables, metadata, FASTA, vendor provenance, "
                    "cross-file relationships, established visualization practices, and missing data."
                ),
                user_messages=[],
                source_manifest=summarize_source_root(source),
                zp_capabilities=build_zp_capabilities(),
                trace_callback=record_trace,
            )
            break
        except KimiHttpError as exc:
            last_error = exc
            if exc.status_code != 401:
                raise
    if result is None:
        assert last_error is not None
        raise last_error
    payload = result.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded, encoding="utf-8")
    used = {item.tool_name for item in result.trace if item.status == "SUCCEEDED"}
    required = {
        "inspect_source_tree",
        "inspect_tabular_file",
        "inspect_mzml",
        "inspect_fasta",
        "validate_scan_relation",
    }
    missing = sorted(required - used)
    if missing:
        raise AssertionError(f"Agent 1 did not use required research tools: {', '.join(missing)}")
    normalized = encoded.casefold().replace(",", "")
    for expected in ("7534", "1431", "6103", "msms.txt"):
        if expected not in normalized:
            raise AssertionError(f"DatasetBlueprint omitted required discovered fact: {expected}")
    print(
        json.dumps(
            {
                "model": result.model,
                "dataset_family": result.blueprint.dataset_family,
                "source_profile": result.blueprint.source_profile,
                "tool_calls": [item.tool_name for item in result.trace],
                "local_tool_calls": result.local_tool_calls,
                "web_search_calls": result.web_search_calls,
                "fetch_calls": result.fetch_calls,
                "source_asset_count": len(result.blueprint.source_assets),
                "entity_count": len(result.blueprint.scientific_entities),
                "binary_section_count": len(result.blueprint.binary_content),
                "visualization_count": len(result.blueprint.visualizations),
                "citation_count": len(result.blueprint.citations),
                "output": str(output) if output else None,
                "trace_output": str(trace_output) if trace_output else None,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
