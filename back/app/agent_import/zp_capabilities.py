"""Machine-readable ZP capabilities injected into model calls and local preflight."""

from __future__ import annotations

import importlib
from typing import Any

from app.zp_runtime.package import ensure_binary_layer_importable


def build_zp_capabilities() -> dict[str, Any]:
    ensure_binary_layer_importable()
    source_adapters = importlib.import_module("binary_layer.source_adapters")
    bottom_up = importlib.import_module("binary_layer.bottom_up_schema")
    composite = importlib.import_module("binary_layer.composite_bottom_up_bundle")
    top_down = importlib.import_module("binary_layer.top_down_schema")
    adapters = source_adapters.build_default_source_adapter_registry().names()
    return {
        "schema_version": 1,
        "target_format_version": 3,
        "writer": "Viewer ZpWriter",
        "logical_blocks": [
            "global_meta",
            "core_runs",
            "core_spectra",
            "core_precursors",
            "core_chromatograms",
            "arrays",
            "indexes",
            "string_pool",
            "extensions",
        ],
        "source_adapters": [item for item in adapters if not item.startswith("mock_")],
        "analysis_categories": ["SPECTRA_ONLY", "TOP_DOWN", "BOTTOM_UP"],
        "extension_types": {
            "bottom_up": list(bottom_up.BOTTOM_UP_EXTENSION_TYPES),
            "top_down": list(top_down.TOP_DOWN_EXTENSION_TYPES),
        },
        "mapping_adapters": {
            "maxquant_mzml_v1": {
                "source_type": composite.SOURCE_TYPE,
                "adapter_flavor": composite.ADAPTER_FLAVOR,
                "source_format": "maxquant_mzml_bundle",
                "analysis_category": "BOTTOM_UP",
                "binary_operation": "convert_declared_mapping_to_zp",
                "target_format_version": 3,
                "identification_kind": bottom_up.BOTTOM_UP_DDA_IDENTIFICATION_KIND,
                "association_contract": (
                    "evidence.txt MS/MS scan number -> unique same-run mzML MS2 Spectrum.scan_number; "
                    "source scan and native ID are persisted"
                ),
                "field_mapping_policy": (
                    "Every declared source_field must physically exist in this bundle. "
                    "Declare only the required canonical mappings below; all other table columns "
                    "are preserved losslessly in source_fields. Do not guess optional columns."
                ),
                "required_field_mappings": [
                    ["evidence", "id", "identification", "evidence_id", "integer", None, "identity"],
                    ["evidence", "Raw file", "run", "raw_file", "string", None, "identity"],
                    ["evidence", "Experiment", "metadata", "experiment_name", "string", None, "identity"],
                    ["evidence", "Sequence", "identification", "sequence", "string", None, "identity"],
                    ["evidence", "Modifications", "identification", "modifications", "string", None, "identity"],
                    ["evidence", "Modified sequence", "identification", "modified_sequence", "string", None, "identity"],
                    ["evidence", "Charge", "identification", "charge", "integer", None, "identity"],
                    ["evidence", "m/z", "identification", "mz", "float", None, "identity"],
                    ["evidence", "Mass", "identification", "mass", "float", None, "identity"],
                    ["evidence", "Retention time", "identification", "retention_time_seconds", "float", None, "minute_to_second"],
                    ["evidence", "MS/MS scan number", "identification", "msms_scan_number", "integer", None, "identity"],
                    ["evidence", "Proteins", "identification", "protein_ids", "string", None, "semicolon_split"],
                    ["evidence", "Protein group IDs", "identification", "protein_group_ids", "string", None, "semicolon_split"],
                    ["evidence", "Score", "identification", "score", "float", None, "identity"],
                    ["evidence", "PEP", "identification", "pep", "float", None, "identity"],
                    ["evidence", "Intensity", "quantification", "evidence_intensity", "float", None, "identity"],
                    ["protein_groups", "id", "protein_group", "protein_group_id", "integer", None, "identity"],
                    ["protein_groups", "Protein IDs", "protein_group", "protein_ids", "string", None, "semicolon_split"],
                    ["protein_groups", "Majority protein IDs", "protein_group", "majority_protein_ids", "string", None, "semicolon_split"],
                    ["protein_groups", "Q-value", "protein_group", "q_value", "float", None, "identity"],
                    ["protein_groups", "Score", "protein_group", "score", "float", None, "identity"],
                    ["protein_groups", "Intensity", "quantification", "protein_group_intensity", "float", None, "identity"],
                    ["protein_groups", "Peptide sequences", "protein_group", "peptide_sequences", "string", None, "semicolon_split"],
                    ["protein_groups", "Potential contaminant", "protein_group", "potential_contaminant", "boolean", None, "plus_marker_to_bool"],
                    ["protein_groups", "Evidence IDs", "protein_group", "evidence_ids", "string", None, "semicolon_split"],
                ],
                "required_join_rules": [
                    ["evidence", "MS/MS scan number", "spectrum_source", "scan_number", "many_to_one", "identity"],
                    ["protein_groups", "Evidence IDs", "evidence", "id", "many_to_one", "semicolon_membership"],
                ],
                "expected_count_keys": [
                    "spectra",
                    "precursors",
                    "evidence_rows",
                    "protein_groups",
                ],
                "unmapped_field_policy": (
                    "unmapped_fields may list only exact physical column names; omit guessed or variant names"
                ),
                "required_roles": {
                    "evidence": {
                        "source_format": "tsv",
                        "required_columns": [
                            "Raw file",
                            "Experiment",
                            "Sequence",
                            "Modifications",
                            "Modified sequence",
                            "Charge",
                            "m/z",
                            "Mass",
                            "Retention time",
                            "MS/MS scan number",
                            "Proteins",
                            "id",
                            "Protein group IDs",
                            "Score",
                            "PEP",
                            "Intensity",
                        ],
                    },
                    "protein_groups": {
                        "source_format": "tsv",
                        "required_columns": [
                            "Protein IDs",
                            "Majority protein IDs",
                            "Q-value",
                            "Score",
                            "Intensity",
                            "Peptide sequences",
                            "Potential contaminant",
                            "id",
                            "Evidence IDs",
                        ],
                    },
                    "parameters": {"source_format": "xml", "required_columns": []},
                    "spectrum_source": {"source_format": "mzml", "required_columns": []},
                    "vendor_raw": {"source_format": "vendor", "required_columns": []},
                    "fasta": {"source_format": "fasta", "required_columns": []},
                },
                "optional_roles": {
                    "summary": {"source_format": "tsv"},
                    "vendor_metadata": {"source_format": "json"},
                },
                "preserves": [
                    "all mzML MS1/MS2 peak arrays",
                    "selected precursors and TIC/BPC chromatograms",
                    "MaxQuant evidence, peptides, proteins, protein groups and ordinary Intensity",
                    "null-versus-zero measurements",
                    "source rows and search/QC metadata",
                ],
                "declared_gaps": [
                    "no b/y fragment annotations when msms.txt is absent",
                    "vendor RAW bytes are hashed provenance and are not embedded",
                    "contaminant sequences absent from the supplied FASTA remain unavailable",
                ],
                "first_version_limits": [
                    "exactly one Raw file value and one mzML run",
                    "one matching Thermo RAW, one mzML and one mqpar-referenced FASTA are mandatory",
                    "mzML-declared RAW SHA-1 must equal the bundled RAW content",
                    "observed peptide modifications are limited to Unmodified and Oxidation (M)",
                    "Acetyl (Protein N-term) is preserved as search vocabulary but is not observed in this profile",
                ],
                "allowed_transforms": [
                    "identity",
                    "minute_to_second",
                    "semicolon_split",
                    "first_semicolon_value",
                    "plus_marker_to_bool",
                ],
            }
        },
    }
