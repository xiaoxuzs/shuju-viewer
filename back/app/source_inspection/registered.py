"""Format contracts backed by existing registered Readers, not filename guesses."""
from pathlib import Path
from contextlib import closing
import sqlite3
import tempfile
from collections import Counter

import pyarrow.parquet as pq

from app.agent_import.execution_control import checkpoint


def registered_contract(root: Path, path: Path):
    if path.suffix.lower() == ".mzml":
        return _thermo_dependent_filter_contract(path)
    if path.suffix.lower() in {".txt", ".tsv"}:
        return _maxquant_table_contract(root, path)
    if not path.name.casefold().endswith(".diaclip.fdr.parquet"):
        return None
    from app.ingest.bu.diaclip_fdr_result_reader import DIACLIP_FDR_COLUMNS, inspect_diaclip_fdr_bundle
    parquet = pq.ParquetFile(path)
    if set(parquet.schema_arrow.names) != set(DIACLIP_FDR_COLUMNS):
        return None
    bundle = inspect_diaclip_fdr_bundle(root)
    if bundle.result_path != path.resolve():
        return None
    # Full identity/type statistics, bounded output. No filtering by decoy/PASSED/q.
    with tempfile.TemporaryDirectory(prefix="viewer-source-statistics-") as temporary:
        with closing(sqlite3.connect(str(Path(temporary) / "keys.sqlite"))) as db:
            db.execute("CREATE TABLE ids(run TEXT,id TEXT,PRIMARY KEY(run,id))")
            duplicates = rows = 0
            missing = Counter()
            for batch in parquet.iter_batches(batch_size=1024):
                checkpoint()
                for row in batch.to_pylist():
                    rows += 1
                    duplicates += db.execute("INSERT OR IGNORE INTO ids VALUES(?,?)", (row["Run"], row["Precursor.Id"])).rowcount == 0
                    for field, value in row.items():
                        if value is None or isinstance(value, str) and not value.strip():
                            missing[field] += 1
            db.commit()
    return {"profile": "diaclip-fdr-reader-v1", "reader": "app.ingest.bu.diaclip_fdr_result_reader",
        "semantics_evidence": "Registered DIA-CLIP FDR Reader passes RT unchanged as minutes to universal_diann_adapter; its source format is single-run DIA. This is format-contract evidence, not magnitude inference.",
        "fields": [{"name": name, **({"unit": "minute"} if name in {"RT", "RT.Start", "RT.Stop", "FWHM"} else {"unit": "source_intensity"} if name == "DIAClip.Quantity" else {})} for name in parquet.schema_arrow.names],
        "quantity_semantics": "source_intensity is the existing Viewer's source-native intensity label, not a calibrated physical unit. Preserve the DIAClip.Quantity metric name; no normalization, channel or sample is inferred.",
        "labelled_channels": False,
        "acquisition_mode": "dia", "rows_scanned": rows, "scan_complete": True,
        "duplicate_run_precursor_ids": duplicates,
        "missing_value_counts": dict(missing),
        "missing_value_scope": "all rows, all physical columns; null and empty/whitespace text counted; no raw diagnostic samples",
        "identity_recommendation": "source_row" if duplicates else "mapped",
        "group_identity": "Protein.Group is one group identifier; use singleton_list for identification.protein_group_ids and semicolon_split for protein_group.member_accessions. Keep Protein.Ids as distinct identification protein associations.",
        "decoy_scope": "Decoy belongs to the identification; use identification.is_decoy, not a protein-label inference.",
        "field_targets": {"Decoy": ["identification.is_decoy"], "DIAClip.Q.Value": ["identification.q_value"],
            "DIAClip.Score": ["identification.score"], "DIAClip.Quantity": ["quantification.value"],
            "Run": ["run.name"], "Stripped.Sequence": ["peptide.sequence"], "Modified.Sequence": ["identification.modified_sequence"],
            "Precursor.Charge": ["identification.charge"], "Precursor.Mz": ["identification.precursor_mz"], "RT": ["identification.rt_seconds"],
            "Protein.Ids": ["identification.protein_accessions", "protein.accession"],
            "Protein.Group": ["identification.protein_group_ids", "protein_group.source_id", "protein_group.member_accessions"],
            "Protein.Names": [], "Genes": []},
        "target_transforms": {"Decoy:identification.is_decoy": ["identity"],
            "Protein.Group:identification.protein_group_ids": ["singleton_list"],
            "Protein.Group:protein_group.source_id": ["identity", "trim"],
            "Protein.Group:protein_group.member_accessions": ["semicolon_split"]},
        "annotation_scope": "Protein.Names and Genes are aggregate row annotations. Preserve them in source_fields; assigning aggregates to each protein is not supported by this contract.",
        "row_policy": "Preserve all rows and reported confidence; ordinary importer filtering is NOT this Case's full-source delivery contract."}


def _maxquant_table_contract(root, path):
    import csv
    import xml.etree.ElementTree as ET
    parameters = root / "mqpar.xml"
    if not parameters.is_file():
        return None
    from app.agent_import.source_code import _linked
    if _linked(parameters) or parameters.stat().st_size > 8 * 1024 * 1024:
        return None
    try:
        tree = ET.parse(parameters)
        if tree.getroot().tag.rsplit("}", 1)[-1] != "MaxQuantParams" or tree.find(".//maxQuantVersion") is None:
            return None
        with path.open(encoding="utf-8-sig", newline="") as stream:
            fields = next(csv.reader(stream, delimiter="\t"), [])
    except (OSError, ET.ParseError, UnicodeError):
        return None
    evidence = {"Raw file", "Sequence", "Modified sequence", "Retention time", "MS/MS scan number", "Protein group IDs", "PEP", "id"}.issubset(fields)
    groups = {"Protein IDs", "Majority protein IDs", "Q-value", "Evidence IDs", "id"}.issubset(fields)
    if not evidence and not groups:
        return None
    return {"profile": "maxquant-reported-table-v1", "parameter_version": tree.findtext(".//maxQuantVersion"),
        "semantics_evidence": "MaxQuantParams plus the table's structural signature identify the reported MaxQuant contract. The existing registered maxquant_composite_bottom_up_v1 reader maps evidence Retention time from minutes, PEP as posterior error probability, and group Q-value only at group scope. No search/FDR is recomputed.",
        "fields": [{"name": field, **({"unit": "minute"} if evidence and field == "Retention time" else {"unit": "source_intensity"} if field == "Intensity" or field.startswith("Intensity ") else {})} for field in fields],
        "quantification_owner": "identification" if evidence else "protein_group",
        "confidence_scope": "PEP is not q_value; proteinGroups Q-value must not be copied to identifications.",
        "intensity_semantics": "Intensity is reported source intensity, not a calibrated physical unit. A suffix on a group Intensity column denotes the reported run/sample, not automatically a labelled channel.",
        "field_targets": ({"Proteins": ["identification.protein_accessions"], "Protein group IDs": ["identification.protein_group_ids"],
            "Experiment": ["quantification.sample"], "PEP": ["identification.pep"], "Intensity": ["quantification.value"]} if evidence else
            {"Protein IDs": ["protein_group.member_accessions", "protein.accession"], "Q-value": ["protein_group.q_value"]}),
        "required_field_targets": ({field: target for field, target in {
            "Proteins": "identification.protein_accessions", "Experiment": "quantification.sample"
        }.items() if field in fields} if evidence else {}),
        "association_semantics": "Evidence Proteins is the reported identification-to-protein association; Protein group IDs is a semicolon-delimited list (including singleton lists), not a substitute for Proteins. Group Protein IDs is the member list. Experiment is the reported sample/experiment label for evidence quantities, not an inferred biological identity or channel. Preserve both associations and the supplied quantity label.",
        "preserve": "all physical fields and rows, including decoy and contaminant markers"}


def _thermo_dependent_filter_contract(path):
    import re
    from lxml import etree
    counts = {"ms2_spectra": 0, "ms2_filters": 0, "thermo_dependent": 0}
    for _, element in etree.iterparse(str(path), events=("end",), load_dtd=False, no_network=True, resolve_entities=False):
        if element.tag.rsplit("}", 1)[-1] == "cvParam" and element.get("accession") == "MS:1000511" and element.get("value") == "2" and element.getparent().tag.rsplit("}", 1)[-1] == "spectrum":
            counts["ms2_spectra"] += 1
        if element.tag.rsplit("}", 1)[-1] == "cvParam" and element.get("accession") == "MS:1000512":
            value = element.get("value", "")
            if re.search(r"\bms2\b", value):
                counts["ms2_filters"] += 1
                if re.match(r"^(?:FTMS|ITMS)\s", value) and re.search(r"\bd\s+Full\s+ms2\b", value):
                    counts["thermo_dependent"] += 1
                if counts["ms2_filters"] % 256 == 0:
                    checkpoint()
        element.clear()
        while element.getprevious() is not None:
            del element.getparent()[0]
    if counts["ms2_spectra"] and counts["ms2_spectra"] == counts["ms2_filters"] == counts["thermo_dependent"]:
        return {"profile": "thermo-dependent-filter-v1", "acquisition_mode": "dda", "scan_complete": True,
            "filter_counts": counts, "semantics_evidence": "All MS2 filter strings (MS:1000512) use Thermo FTMS/ITMS 'd Full ms2': d is the vendor's explicit data-dependent scan flag. This is not inferred from software name, scan numbers or precursor-count heuristics."}
    return None
