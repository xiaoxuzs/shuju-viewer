#!/usr/bin/env python3
"""Convert and deeply verify the real single-sample MaxQuant + mzML composite bundle."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "back"
sys.path.insert(0, str(BACKEND_ROOT))

from app.zp_runtime.package import ensure_binary_layer_importable  # noqa: E402

ensure_binary_layer_importable()

from binary_layer import BottomUpReader, ZpReader, convert_source_to_zp, validate_zp  # type: ignore[import-not-found]  # noqa: E402


DEFAULT_SOURCE = (
    REPO_ROOT.parent
    / "viewer-agent"
    / "maxquant"
    / "maxquant-viz-data"
    / "single-sample"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    source = args.source.expanduser().resolve(strict=True)

    if args.output is None:
        (REPO_ROOT / ".tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="maxquant-composite-acceptance-",
            dir=REPO_ROOT / ".tmp",
        ) as temporary:
            _run(source, Path(temporary) / "single-sample.zp")
        return
    _run(source, args.output.expanduser().resolve(strict=False))


def _run(source: Path, output: Path) -> None:
    result = convert_source_to_zp(source, output, format_version=3)
    if not result.validation.valid or result.validation.bottom_up_valid is not True:
        raise AssertionError("conversion did not pass integrated Bottom-Up validation")
    reader = ZpReader(output)
    spectra = reader.read_spectra()
    precursors = reader.read_precursors()
    chromatograms = reader.read_chromatograms()
    arrays = reader.read_arrays()
    bottom_up = BottomUpReader(output)
    summary = bottom_up.get_bottom_up_summary()
    payloads = bottom_up.get_extension_payloads()
    metadata = bottom_up.get_metadata()
    identifications = payloads["bottom_up_identifications"]["records"]
    quantification = payloads["bottom_up_quantification"]["records"]
    modifications = payloads["bottom_up_modifications"]["records"]

    actual = {
        "spectra": len(spectra),
        "ms1": sum(item.ms_level == 1 for item in spectra),
        "ms2": sum(item.ms_level == 2 for item in spectra),
        "precursors": len(precursors),
        "peak_pairs": sum(len(item.values) for item in arrays if item.array_type == "mz"),
        "chromatograms": len(chromatograms),
        "bpc_points": (
            len(reader.read_array(chromatograms[0].time_array_id).values)
            if chromatograms else 0
        ),
        "identifications": summary["identification"],
        "peptides": summary["peptide"],
        "proteins": summary["protein"],
        "protein_groups": summary["protein_group"],
        "modifications": summary["modification"],
        "quantification": summary["quantification"],
        "exact_ms2_links": sum(
            item["association_kind"] == "exact_scan_number"
            and isinstance(item["source_scan"], int)
            and isinstance(item["source_native_id"], str)
            for item in identifications
        ),
        "null_evidence_intensity": sum(
            item["entity_kind"] == "identification"
            and item["measurements"].get("intensity") is None
            for item in quantification
        ),
        "zero_group_intensity": sum(
            item["entity_kind"] == "protein_group"
            and item["measurements"].get("intensity") == 0
            for item in quantification
        ),
    }
    expected = {
        "spectra": 7534,
        "ms1": 1431,
        "ms2": 6103,
        "precursors": 6103,
        "peak_pairs": 3949930,
        "chromatograms": 1,
        "bpc_points": 7534,
        "identifications": 35,
        "peptides": 32,
        "proteins": 33,
        "protein_groups": 32,
        "modifications": 1,
        "quantification": 67,
        "exact_ms2_links": 35,
        "null_evidence_intensity": 15,
        "zero_group_intensity": 15,
    }
    if actual != expected:
        raise AssertionError(f"semantic counts differ: {actual}")
    if metadata["raw_mzml_identity"] != {
        "algorithm": "SHA-1",
        "declared_by_mzml": "5e050c8abc697891e2286271e062a8144518108a",
        "computed_from_raw": "5e050c8abc697891e2286271e062a8144518108a",
        "match": True,
    }:
        raise AssertionError("RAW-to-mzML SHA-1 identity was not preserved")
    if len(modifications) != 1 or modifications[0].get("source_protein_sites") != "113":
        raise AssertionError("observed Oxidation (M) peptide/protein site was not preserved")
    source_hashes = {item["role"]: item["sha256"] for item in metadata["source_files"]}
    if source_hashes["vendor_raw"] != "a6adae7944ca2d1f09e5308689ea8f102a3c9d3b2dcce53563d5bfca054c39c5":
        raise AssertionError("RAW SHA-256 differs")
    if source_hashes["spectrum_source"] != "e7b2afdc5a115038324bcb8814d59752d1a6a49cc3015cdb23e118b8046abad6":
        raise AssertionError("mzML SHA-256 differs")
    deep = validate_zp(output, mode="deep")
    if not deep.valid or deep.bottom_up_valid is not True:
        raise AssertionError("independent deep validation failed")
    print(
        json.dumps(
            {
                "status": "PASSED",
                "source_type": result.source_profile.source_type,
                "output": str(output),
                "output_size": result.output_file_size,
                "output_sha256": result.output_sha256,
                "counts": actual,
                "deep_validation": {
                    "valid": deep.valid,
                    "bottom_up_valid": deep.bottom_up_valid,
                    "issue_count": len(deep.issues) + len(deep.bottom_up_issues),
                },
                "performance": result.performance,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
