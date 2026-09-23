"""Fixed trusted process: all source/ZP/projection/API records; bounded browser sample manifest."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import time
from urllib.request import urlopen

from app.agent_import.verification_full import (FullAcceptanceContract, FullVerificationError, ReconciliationLedger,
    populate_source, reconcile_semantic, encoded, record_key)
from app.agent_import.verification_http_full import reconcile_http, reconcile_entity_http, API_FIELDS
from app.agent_import.verification_metrics import peak_rss_bytes
from app.agent_import.input_assets import content_manifest, hash_file


def projection_records(session, dataset_id, batch_size, table=None):
    from sqlalchemy import text
    statement = text("""SELECT im.match_id,im.run_id,im.entity_id AS peptide_id,p.sequence,im.modified_sequence,im.retention_time,
        im.q_value,im.score,im.precursor_charge,im.precursor_mz,im.intensity,im.is_decoy_match,im.extra_metadata,im.pep,im.experimental_mass
        FROM identification_matches im JOIN peptides p ON p.dataset_id=im.dataset_id AND p.peptide_id=im.entity_id
        WHERE im.dataset_id=:dataset_id AND im.entity_type='PEPTIDE' ORDER BY im.match_id""").execution_options(stream_results=True, yield_per=batch_size)
    for row in session.execute(statement, {"dataset_id": dataset_id}).mappings():
        metadata = row["extra_metadata"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        quant = [{k: q.get(k) for k in ("value", "unit", "metric", "channel", "sample", "normalization_kind")} for q in metadata.get("quantification", [])]
        decoy = row["is_decoy_match"] if metadata.get("is_decoy_state") == "DIRECT" else None
        record = {"run": metadata.get("source_run_name"), "source_id": metadata.get("source_record_id"),
                  "sequence": row["sequence"], "modified_sequence": row["modified_sequence"],
                  "rt_seconds": row["retention_time"] * 60 if row["retention_time"] is not None else None,
                  "q_value": row["q_value"], "score": row["score"], "charge": row["precursor_charge"], "precursor_mz": row["precursor_mz"],
                  "decoy": decoy, "proteins": sorted(metadata.get("protein_accessions", [])),
                  "groups": {g["source_group"]: sorted(g["members"]) for g in metadata.get("protein_groups", [])},
                  "quantification": quant, "source_fields": metadata.get("source_fields"),
                  "source_relative_path": metadata.get("source_relative_path"), "source_row_number": metadata.get("source_row_number")}
        for name, value in (("pep", row["pep"]), ("neutral_mass", row["experimental_mass"]), ("scan", metadata.get("source_scan"))):
            if table is not None and getattr(table, name + "_column"):
                record[name] = value
        api = {"source_record_id": record["source_id"], "source_run_name": record["run"], "source_relative_path": record["source_relative_path"],
               "sequence": row["sequence"], "modified_sequence": row["modified_sequence"], "precursor_mz": row["precursor_mz"],
               "precursor_charge": row["precursor_charge"], "retention_time": row["retention_time"], "q_value": row["q_value"],
               "score": row["score"], "intensity": row["intensity"], "is_decoy_match": decoy,
               "protein_accessions": record["proteins"], "run_id": row["run_id"], "peptide_id": row["peptide_id"]}
        yield row["match_id"], record, api


def check_projected_intensity(ledger, record, api):
    """Flat SQL/API intensity must agree with the independent source contract.

    v2 declares one unchannelled identification quantity. Unknown/non-intensity
    units remain in structured quantification, not the legacy intensity column.
    Comparing HTTP only to SQL would otherwise let the same corrupted value pass.
    """
    from .verification_full import unequal
    raw = ledger.db.execute("SELECT body FROM expected WHERE k=?", (record_key(record),)).fetchone()
    if raw is None:
        raise FullVerificationError("PROJECTION_UNKNOWN_IDENTITY")
    source = json.loads(raw[0])
    values = source["quantification"]
    expected = values[0]["value"] if values and ledger.contract.table.quantity_unit in {"source_intensity", "intensity"} else None
    if unequal(expected, api["intensity"], absolute=ledger.contract.numeric_absolute_tolerance, relative=ledger.contract.numeric_relative_tolerance):
        raise FullVerificationError("PROJECTION_INTENSITY_SOURCE_MISMATCH")


def check_spectra(candidate, root, contract, check, progress=None):
    paths = [p for p, role in contract.source_roles.items() if role == "spectra"]
    if not paths:
        return {"coverage": "not_applicable", "spectra": 0}
    if len(paths) != 1 or not paths[0].lower().endswith(".mzml"):
        raise FullVerificationError("FULL_SPECTRUM_RECIPE_NOT_SUPPORTED")
    import numpy as np
    import re
    from pyteomics import mzml
    from app.zp_runtime.package import ensure_binary_layer_importable
    ensure_binary_layer_importable()
    from binary_layer import ZpReader
    reader = ZpReader(candidate)
    spectra = reader.read_spectra()
    by_native = {s.native_id: s for s in spectra}
    precursors = {p.precursor_id: p for p in reader.read_precursors()}
    if len(by_native) != len(spectra):
        raise FullVerificationError("DUPLICATE_CORE_NATIVE_ID")
    count = peaks = 0
    with mzml.MzML(str(root / paths[0]), use_index=False) as source:
        for item in source:
            if count % 64 == 0:
                check()
                if progress:
                    progress("spectra", count, None)
            spectrum = by_native.pop(item["id"], None)
            if spectrum is None or spectrum.ms_level != int(item["ms level"]):
                raise FullVerificationError("CORE_SOURCE_SPECTRUM_IDENTITY_MISMATCH")
            match = re.search(r"(?:^|\s)scan=(\d+)(?:\s|$)", item["id"])
            if match is None or spectrum.scan_number != int(match.group(1)):
                raise FullVerificationError("CORE_DECLARED_SCAN_ID_MISMATCH")
            source_precursors = item.get("precursorList", {}).get("precursor", [])
            if spectrum.ms_level == 1:
                if spectrum.precursor_id is not None:
                    raise FullVerificationError("CORE_INVENTED_PRECURSOR")
            else:
                if len(source_precursors) != 1 or spectrum.precursor_id not in precursors:
                    raise FullVerificationError("CORE_PRECURSOR_SCOPE_MISMATCH")
                actual = precursors.pop(spectrum.precursor_id)
                isolation = source_precursors[0].get("isolationWindow", {})
                center = isolation.get("isolation window target m/z")
                low, high = isolation.get("isolation window lower offset"), isolation.get("isolation window upper offset")
                if contract.acquisition_mode == "dia":
                    if center is None or low is None or high is None or actual.precursor_mz is not None or actual.charge is not None:
                        raise FullVerificationError("CORE_DIA_ISOLATION_CONTRACT_MISMATCH")
                    if actual.spectrum_id != spectrum.spectrum_id or actual.isolation_lower_mz != float(center) - float(low) or actual.isolation_upper_mz != float(center) + float(high):
                        raise FullVerificationError("CORE_ISOLATION_VALUES_MISMATCH")
                else:
                    ions = source_precursors[0].get("selectedIonList", {}).get("selectedIon", [])
                    if len(ions) != 1 or actual.spectrum_id != spectrum.spectrum_id:
                        raise FullVerificationError("CORE_DDA_PRECURSOR_SCOPE_MISMATCH")
                    ion = ions[0]
                    if (actual.precursor_mz != float(ion["selected ion m/z"]) or actual.charge != int(ion["charge state"])
                            or actual.intensity != float(ion["peak intensity"])):
                        raise FullVerificationError("CORE_DDA_PRECURSOR_VALUES_MISMATCH")
            scan = item["scanList"]["scan"][0]["scan start time"]
            unit = str(getattr(scan, "unit_info", "")).lower()
            if unit not in {"minute", "second"}:
                raise FullVerificationError("MZML_RT_UNIT_NOT_DECLARED")
            rt = float(scan) * (60 if unit == "minute" else 1)
            if abs(spectrum.rt - rt) > 1e-7:
                raise FullVerificationError("CORE_RT_MISMATCH")
            # Metadata was indexed once above; read_spectrum_arrays reconstructs the
            # entire spectrum metadata list on each call and is quadratic for a full scan.
            mz_values, intensity = reader.read_arrays_by_ids([spectrum.mz_array_id, spectrum.intensity_array_id])
            if not np.array_equal(np.asarray(mz_values.values), item["m/z array"]) or not np.array_equal(np.asarray(intensity.values), item["intensity array"]):
                raise FullVerificationError("CORE_PEAK_ARRAY_MISMATCH")
            peaks += len(item["m/z array"])
            count += 1
    if by_native:
        raise FullVerificationError("EXTRA_CORE_SPECTRA")
    if precursors:
        raise FullVerificationError("EXTRA_CORE_PRECURSORS")
    # Pyteomics decodes the arrays but does not retain their unit attributes.
    # Read CV unit declarations independently, without decoding binary XML ourselves.
    from lxml import etree
    time_units = {}
    for _, element in etree.iterparse(str(root / paths[0]), events=("end",), load_dtd=False, no_network=True, resolve_entities=False):
        local = element.tag.rsplit("}", 1)[-1]
        if local == "cvParam" and element.get("accession") == "MS:1000595":
            parent = element.getparent()
            while parent is not None and parent.tag.rsplit("}", 1)[-1] not in {"chromatogram", "spectrum"}:
                parent = parent.getparent()
            if parent is not None and parent.tag.rsplit("}", 1)[-1] == "chromatogram":
                unit = element.get("unitAccession")
                if unit not in {"UO:0000031", "UO:0000010"}:
                    raise FullVerificationError("MZML_CHROMATOGRAM_UNIT_UNKNOWN")
                time_units[parent.get("id")] = 60 if unit == "UO:0000031" else 1
        if local in {"spectrum", "chromatogram"}:
            element.clear()
            while element.getprevious() is not None:
                del element.getparent()[0]
    chromatograms = {c.native_id: c for c in reader.read_chromatograms()}
    chromatogram_count = 0
    with mzml.MzML(str(root / paths[0]), use_index=False) as source:
        for item in source.iterfind("chromatogram"):
            check()
            actual = chromatograms.pop(item["id"], None)
            if actual is None or item["id"] not in time_units:
                raise FullVerificationError("CORE_CHROMATOGRAM_IDENTITY_MISMATCH")
            _, times, intensity = reader.read_chromatogram_arrays(actual.chromatogram_id)
            expected_times = np.asarray(item["time array"], dtype=np.float64) * time_units[item["id"]]
            if not np.array_equal(np.asarray(times.values), expected_times) or not np.array_equal(np.asarray(intensity.values), item["intensity array"]):
                raise FullVerificationError("CORE_CHROMATOGRAM_VALUE_MISMATCH")
            chromatogram_count += 1
    if chromatograms:
        raise FullVerificationError("EXTRA_CORE_CHROMATOGRAM")
    return {"coverage": "all_source_spectra_and_peak_values", "spectra": count, "peaks": peaks,
            "chromatograms": chromatogram_count, "metadata": "native ID, declared scan, MS level, RT and mode-specific precursor values checked for all spectra; all declared chromatogram time/intensity points checked",
            "external_preservation": "Auxiliary chromatogram arrays and other mzML CV terms remain in the complete content-verified source asset; no unsupported core representation is claimed.",
            "correlation_risk": "Independent pyteomics source decode; ZpReader is the deployed Reader. Deep Writer validation is additional, not the oracle."}


def run(args):
    if os.environ.get("VIEWER_ENV") != "test" or not os.environ.get("VIEWER_BUILD_ID"):
        raise RuntimeError("Full verification requires identified isolated test process")
    from sqlalchemy import text
    from app.core.db import SessionLocal
    from app.declarative_ingest import read_semantic_zp
    contract = FullAcceptanceContract.model_validate_json(args.oracle.read_text(encoding="utf-8"))
    ledger = ReconciliationLedger(args.output.with_suffix(".sqlite"), contract)
    def progress(phase, processed, total):
        args.output.with_name("full-progress.json").write_text(json.dumps({"phase": phase, "processed": processed, "total": total}), encoding="utf-8")
    ledger.progress = progress
    report = {"verifier_version": contract.verifier_version, "status": "FAILED", "timings": {}, "coverage": {}}
    started = time.monotonic()
    candidate_hash = hash_file(args.candidate)
    source_stats = {p: ((args.input_root / p).stat().st_size, (args.input_root / p).stat().st_mtime_ns) for p in contract.source_roles}
    def phase(name, callback):
        begin = time.monotonic()
        value = callback()
        report["timings"][name] = time.monotonic() - begin
        return value
    def get_json(url):
        with urlopen(url, timeout=30) as response:
            return json.loads(response.read(4 * 1024 * 1024))
    try:
        report["coverage"]["source"] = phase("source", lambda: populate_source(ledger, args.input_root))
        dataset = phase("zp_readback", lambda: read_semantic_zp(args.candidate))
        manifest = content_manifest(args.input_root)
        expected_sources = {p for p, role in contract.source_roles.items() if role != "provenance"}
        if {f.relative_path for f in dataset.source_files} != expected_sources or any(
            f.sha256 != manifest["files"][f.relative_path]["sha256"] or f.size_bytes != manifest["files"][f.relative_path]["size"] for f in dataset.source_files
        ):
            raise FullVerificationError("SEMANTIC_SOURCE_MANIFEST_MISMATCH")
        report["coverage"]["semantic"] = phase("semantic", lambda: reconcile_semantic(ledger, dataset))
        report["coverage"]["spectra"] = phase("spectra", lambda: check_spectra(args.candidate, args.input_root, contract, ledger.check, progress))
        del dataset
        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
            session.execute(text("LOCK TABLE identification_matches,peptides,proteins,protein_relation_mapping,runs,dataset_zp_assets IN SHARE MODE"))
            dataset_id = session.execute(text("SELECT dataset_id FROM datasets WHERE slug=:slug"), {"slug": args.slug}).scalar_one()
            def projection():
                for n, (match_id, record, api) in enumerate(projection_records(session, dataset_id, contract.batch_size, contract.table)):
                    if n % contract.batch_size == 0:
                        ledger.check()
                        ledger.db.commit()
                    ledger.compare("projection", record)
                    check_projected_intensity(ledger, record, api)
                    ledger.db.execute("INSERT INTO projection_ids VALUES(?,?,?)", (match_id, record_key(record), encoded(api)))
                return ledger.finish("projection")
            report["coverage"]["projection"] = phase("projection", projection)
            ledger.db.executescript("""CREATE TABLE api_entities(kind TEXT,id INTEGER,body TEXT,PRIMARY KEY(kind,id));
                CREATE TABLE peptide_stats AS SELECT json_extract(body,'$.sequence') AS name,
                    sum(CASE WHEN json_extract(body,'$.decoy') IS 1 THEN 0 ELSE 1 END) AS matches
                    FROM expected GROUP BY name;
                CREATE UNIQUE INDEX peptide_stat_key ON peptide_stats(name);
                CREATE TABLE protein_stats AS SELECT j.value AS name,count(*) AS matches,
                    count(DISTINCT json_extract(e.body,'$.sequence')) AS peptides
                    FROM expected e,json_each(e.body,'$.proteins') j GROUP BY j.value;
                CREATE UNIQUE INDEX protein_stat_key ON protein_stats(name);""")
            for row in session.execute(text("SELECT peptide_id,sequence FROM peptides WHERE dataset_id=:id").execution_options(stream_results=True, yield_per=contract.batch_size), {"id": dataset_id}):
                stat = ledger.db.execute("SELECT matches FROM peptide_stats WHERE name=?", (row.sequence,)).fetchone()
                members = ledger.db.execute("SELECT count(*) FROM source_edges WHERE peptide=?", (row.sequence,)).fetchone()[0]
                if stat is None:
                    raise FullVerificationError("PROJECTION_UNEXPECTED_PEPTIDE")
                ledger.db.execute("INSERT INTO api_entities VALUES('peptides',?,?)", (row.peptide_id, encoded({"sequence": row.sequence, "match_count": stat[0], "protein_count": members})))
            for row in session.execute(text("SELECT protein_id,accession FROM proteins WHERE dataset_id=:id").execution_options(stream_results=True, yield_per=contract.batch_size), {"id": dataset_id}):
                stat = ledger.db.execute("SELECT matches,peptides FROM protein_stats WHERE name=?", (row.accession,)).fetchone() or (0, 0)
                ledger.db.execute("INSERT INTO api_entities VALUES('proteins',?,?)", (row.protein_id, encoded({"accession": row.accession, "match_count": stat[0], "peptide_count": stat[1]})))
            for row in session.execute(text("""SELECT p.sequence,pr.accession FROM protein_relation_mapping rm
                    LEFT JOIN peptides p ON p.dataset_id=rm.dataset_id AND p.peptide_id=rm.entity_id
                    LEFT JOIN proteins pr ON pr.dataset_id=rm.dataset_id AND pr.protein_id=rm.protein_id
                    WHERE rm.dataset_id=:id AND rm.entity_type='PEPTIDE'""").execution_options(stream_results=True, yield_per=contract.batch_size), {"id": dataset_id}):
                if ledger.db.execute("DELETE FROM source_edges WHERE peptide=? AND protein=?", (row.sequence, row.accession)).rowcount != 1:
                    raise FullVerificationError("PROJECTION_RELATION_WRONG_OR_DUPLICATE")
            if ledger.db.execute("SELECT count(*) FROM source_edges").fetchone()[0]:
                raise FullVerificationError("PROJECTION_RELATION_MISSING")
            for kind, statement in (("peptide", "SELECT sequence FROM peptides WHERE dataset_id=:id"),
                                    ("protein", "SELECT accession FROM proteins WHERE dataset_id=:id")):
                for value, in session.execute(text(statement).execution_options(stream_results=True, yield_per=contract.batch_size), {"id": dataset_id}):
                    if ledger.db.execute("DELETE FROM source_entities WHERE kind=? AND k=?", (kind, value)).rowcount != 1:
                        raise FullVerificationError("PROJECTION_EXTRA_ENTITY")
            if ledger.db.execute("SELECT count(*) FROM source_entities WHERE kind IN ('peptide','protein')").fetchone()[0]:
                raise FullVerificationError("PROJECTION_ENTITY_MISSING")
            report["coverage"]["http"] = phase("http", lambda: reconcile_http(ledger, get_json, args.api_url + "/api/v1/datasets/" + args.slug))
            for entity in ("peptides", "proteins"):
                report["coverage"]["http_" + entity] = phase("http_" + entity, lambda entity=entity: reconcile_entity_http(ledger, get_json, args.api_url + "/api/v1/datasets/" + args.slug, entity))
        if hash_file(args.candidate) != candidate_hash or content_manifest(args.input_root)["sha256"] != contract.source_identity:
            raise FullVerificationError("INPUT_CHANGED_DURING_VERIFICATION")
        if source_stats != {p: ((args.input_root / p).stat().st_size, (args.input_root / p).stat().st_mtime_ns) for p in contract.source_roles}:
            raise FullVerificationError("INPUT_METADATA_CHANGED_DURING_VERIFICATION")
        total = ledger.db.execute("SELECT count(*) FROM expected").fetchone()[0]
        ordinals = sorted({1, min(101, total), min(contract.batch_size, total), total})
        samples = []
        for ordinal in ordinals:
            raw, match_id, api_raw = ledger.db.execute("SELECT e.body,p.id,p.body FROM expected e JOIN projection_ids p ON p.k=e.k WHERE e.ordinal=?", (ordinal,)).fetchone()
            value, api = json.loads(raw), json.loads(api_raw)
            samples.append({"source_record_id": value["source_id"], "match_id": match_id, "run_id": api["run_id"], "sequence": value["sequence"],
                "rt_minutes": value["rt_seconds"] / 60 if value["rt_seconds"] is not None else None,
                "q_value": value["q_value"], "decoy": value["decoy"], "quantification_values": [q["value"] for q in value["quantification"]],
                "quantification_units": [q["unit"] for q in value["quantification"]]})
        report["browser_oracle"] = {"schema_version": 2, "total_matches": total, "matches": samples, "coverage": "representative UI only; full backend reconciliation separately enforced"}
        report["status"] = "PASSED"
    except FullVerificationError as exc:
        report.update(failure_code=exc.code, diagnostic=exc.report)
        raise
    finally:
        ledger.close()
        report.update(elapsed_seconds=time.monotonic() - started, peak_rss_bytes=peak_rss_bytes(), ledger_bytes=ledger.path.stat().st_size,
                      memory_scope="This verification child; semantic Reader still materializes the dataset", candidate_sha256=candidate_hash)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    for name in ("candidate", "input-root", "oracle", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--slug", required=True)
    run(parser.parse_args())


if __name__ == "__main__":
    main()
