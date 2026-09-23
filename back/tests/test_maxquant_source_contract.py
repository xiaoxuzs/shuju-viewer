from app.source_inspection.registered import registered_contract
from app.declarative_ingest.preflight import _observation_supports_unit


def test_maxquant_units_require_parameter_and_header_contract_not_filename(tmp_path):
    table = tmp_path / "renamed.tsv"
    header = "Raw file\tSequence\tModified sequence\tRetention time\tMS/MS scan number\tProtein group IDs\tPEP\tid\tIntensity\n"
    table.write_text(header)
    assert registered_contract(tmp_path, table) is None
    (tmp_path / "mqpar.xml").write_text("<MaxQuantParams><maxQuantVersion>2.8.1.0</maxQuantVersion></MaxQuantParams>")
    contract = registered_contract(tmp_path, table)
    assert contract["quantification_owner"] == "identification"
    observation = {"relative_path": table.name, "facts": {"columns": [{"name": "Retention time"}], **contract}}
    assert _observation_supports_unit(observation, table.name, "Retention time", "minute")
    assert "PEP is not q_value" in contract["confidence_scope"]


def test_mode_needs_explicit_vendor_dependent_flag_for_every_ms2(tmp_path):
    path = tmp_path / "anything.mzML"
    def scan(filter_value=None):
        return '<spectrum><cvParam accession="MS:1000511" value="2"/>' + (f'<cvParam accession="MS:1000512" value="{filter_value}"/>' if filter_value else '') + '</spectrum>'
    dependent = "FTMS + p NSI d Full ms2 600@hcd30 [100-1200]"
    path.write_text("<mzML>"+scan(dependent)+"</mzML>")
    assert registered_contract(tmp_path, path)["acquisition_mode"] == "dda"
    path.write_text("<mzML>"+scan(dependent)+scan()+"</mzML>")
    assert registered_contract(tmp_path, path) is None
    path.write_text("<mzML>"+scan("FTMS + p NSI Full ms2 600 [100-1200]")+"</mzML>")
    assert registered_contract(tmp_path, path) is None
