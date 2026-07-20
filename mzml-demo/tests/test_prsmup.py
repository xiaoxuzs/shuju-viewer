from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "prsmup.py"


def _load_prsmup() -> ModuleType:
    spec = importlib.util.spec_from_file_location("viewer_prsmup", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PRSMUP = _load_prsmup()


def _entry(mass_shifts: list[dict[str, object]]) -> dict[str, object]:
    return {
        "prsm_id": "7",
        "spectrum_scan": 7,
        "p_value": "0.001",
        "e_value": "0.002",
        "fdr": "0.01",
        "start_pos": 0,
        "end_pos": 2,
        "proteo_db_seq": "ACD",
        "proteo_match_seq": "ACD",
        "seq_name": "P00001",
        "seq_desc": "fixture protein",
        "n_term_form": "NONE",
        "mass_shifts": mass_shifts,
    }


def _msalign(scan: int = 7) -> dict[str, object]:
    return {
        "FILE_NAME": "run.mzML",
        "SPECTRUM_ID": str(scan),
        "SCANS": str(scan),
        "PRECURSOR_MASS": "300.0",
        "PRECURSOR_CHARGE": "3",
        "PRECURSOR_MZ": "100.0",
        "peaks": [],
    }


def _annotation(payload: dict[str, object]) -> dict[str, object]:
    prsm = payload["prsm"]
    assert isinstance(prsm, dict)
    protein = prsm["annotated_protein"]
    assert isinstance(protein, dict)
    annotation = protein["annotation"]
    assert isinstance(annotation, dict)
    return annotation


def _mass_shifts(payload: dict[str, object]) -> list[dict[str, object]]:
    value = _annotation(payload).get("mass_shift")
    if value is None:
        return []
    if isinstance(value, list):
        return value
    assert isinstance(value, dict)
    return [value]


def _read_prsm(path: Path) -> dict[str, object]:
    value = path.read_text(encoding="utf-8").split("=", 1)[1]
    parsed = json.loads(value)
    assert isinstance(parsed, dict)
    return parsed


def _write_xml(path: Path) -> None:
    records = [
        (10, 110, "0.03", []),
        (20, 120, "0.01", [(0, 1, 42.010565, "Protein variable")]),
        (
            30,
            130,
            "0.02",
            [
                (0, 1, 42.010565, "Protein variable"),
                (1, 2, 42.010565, "Unexpected"),
                (1, 2, -17.026549, "Unexpected"),
            ],
        ),
    ]
    prsms: list[str] = []
    for prsm_id, scan, e_value, shifts in records:
        shift_xml = "".join(
            "<mass_shift>"
            f"<left_bp_pos>{left}</left_bp_pos>"
            f"<right_bp_pos>{right}</right_bp_pos>"
            f"<shift>{shift}</shift>"
            "<alteration_list><alteration><alter_type>"
            f"<name>{shift_type}</name>"
            "</alter_type></alteration></alteration_list>"
            "</mass_shift>"
            for left, right, shift, shift_type in shifts
        )
        prsms.append(
            "<prsm>"
            f"<prsm_id>{prsm_id}</prsm_id>"
            f"<spectrum_id>{scan}</spectrum_id>"
            f"<spectrum_scan>{scan}</spectrum_scan>"
            f"<extreme_value><p_value>0.001</p_value><e_value>{e_value}</e_value></extreme_value>"
            "<fdr>0.01</fdr><proteoform>"
            "<start_pos>0</start_pos><end_pos>2</end_pos>"
            "<proteo_db_seq>ACD</proteo_db_seq><proteo_match_seq>ACD</proteo_match_seq>"
            "<fasta_seq><seq_name>P00001</seq_name><seq_desc>fixture protein</seq_desc></fasta_seq>"
            "<prot_mod><name>NONE</name></prot_mod>"
            f"<mass_shift_list>{shift_xml}</mass_shift_list>"
            "</proteoform></prsm>"
        )
    path.write_text("<prsm_list>" + "".join(prsms) + "</prsm_list>", encoding="utf-8")


def _write_msalign(path: Path) -> None:
    blocks = []
    for scan in (110, 120, 130):
        blocks.append(
            "BEGIN IONS\n"
            "FILE_NAME=run.mzML\n"
            f"SPECTRUM_ID={scan}\nSCANS={scan}\n"
            "PRECURSOR_MASS=300.0\nPRECURSOR_CHARGE=3\nPRECURSOR_MZ=100.0\n"
            "149.0 500.0 3 1.0\nEND IONS\n"
        )
    path.write_text("".join(blocks), encoding="utf-8", newline="")


def _run_cli(xml: Path, msalign: Path, out_dir: Path, limit: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--prsm-xml",
            str(xml),
            "--msalign",
            str(msalign),
            "--out-dir",
            str(out_dir),
            "--limit",
            str(limit),
        ],
        shell=False,
        check=False,
        capture_output=True,
        text=True,
    )


class PrsmupMassShiftTests(unittest.TestCase):
    def test_zero_mass_shift_preserves_omission_contract(self) -> None:
        payload = PRSMUP.build_prsm_js(_entry([]), _msalign(), {})

        self.assertNotIn("mass_shift", _annotation(payload))
        self.assertEqual(_mass_shifts(payload), [])

    def test_single_mass_shift_preserves_existing_object_contract(self) -> None:
        payload = PRSMUP.build_prsm_js(
            _entry([{"left": 1, "right": 2, "shift": 15.5, "type": "unexpected"}]),
            _msalign(),
            {},
        )

        raw = _annotation(payload)["mass_shift"]
        self.assertIsInstance(raw, dict)
        self.assertEqual(
            raw,
            {
                "id": "0",
                "left_position": "1",
                "right_position": "2",
                "shift": "15.5000000000",
                "anno": "+15.5000",
                "shift_type": "unexpected",
            },
        )

    def test_three_mass_shifts_preserve_xml_order_and_do_not_deduplicate(self) -> None:
        payload = PRSMUP.build_prsm_js(
            _entry(
                [
                    {"left": 0, "right": 1, "shift": 42.010565, "type": "protein variable"},
                    {"left": 1, "right": 2, "shift": 42.010565, "type": "unexpected"},
                    {"left": 1, "right": 2, "shift": -17.026549, "type": "unexpected"},
                ]
            ),
            _msalign(),
            {},
        )

        shifts = _mass_shifts(payload)
        self.assertEqual(len(shifts), 3)
        self.assertEqual([item["id"] for item in shifts], ["0", "1", "2"])
        self.assertEqual(
            [(item["left_position"], item["right_position"], item["shift"]) for item in shifts],
            [
                ("0", "1", "42.0105650000"),
                ("1", "2", "42.0105650000"),
                ("1", "2", "-17.0265490000"),
            ],
        )
        self.assertIsNot(shifts[0], shifts[1])
        self.assertIsNot(shifts[1], shifts[2])

    def test_cli_mixed_prsms_limit_and_determinism(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            xml = root / "run_ms2_toppic_prsm.xml"
            msalign = root / "run_ms2.msalign"
            _write_xml(xml)
            _write_msalign(msalign)

            full_a = root / "full-a"
            full_b = root / "full-b"
            limited = root / "limited"
            result_a = _run_cli(xml, msalign, full_a, 3)
            result_b = _run_cli(xml, msalign, full_b, 3)
            result_limited = _run_cli(xml, msalign, limited, 2)

            self.assertEqual(result_a.returncode, 0, result_a.stderr)
            self.assertEqual(result_b.returncode, 0, result_b.stderr)
            self.assertEqual(result_limited.returncode, 0, result_limited.stderr)
            self.assertEqual(
                {path.name: len(_mass_shifts(_read_prsm(path))) for path in full_a.glob("prsm*.js")},
                {"prsm10.js": 0, "prsm20.js": 1, "prsm30.js": 3},
            )
            self.assertEqual(
                {path.name for path in limited.glob("prsm*.js")},
                {"prsm20.js", "prsm30.js"},
            )
            bytes_a = {path.name: path.read_bytes() for path in full_a.glob("prsm*.js")}
            bytes_b = {path.name: path.read_bytes() for path in full_b.glob("prsm*.js")}
            self.assertEqual(bytes_a, bytes_b)
            self.assertEqual(
                {name: hashlib.sha256(body).hexdigest() for name, body in bytes_a.items()},
                {name: hashlib.sha256(body).hexdigest() for name, body in bytes_b.items()},
            )


if __name__ == "__main__":
    unittest.main()
