from __future__ import annotations

from pathlib import Path

from app.zp_runtime.package import ensure_binary_layer_importable


def test_topfd_js_bundle_converts_to_readable_zp(tmp_path: Path) -> None:
    ensure_binary_layer_importable()
    from binary_layer import ConversionOptions, convert_source_to_zp, inspect_source, open_zp, validate_zp

    source = tmp_path / "source"
    ms1_dir = source / "topfd" / "ms1_json"
    ms2_dir = source / "topfd" / "ms2_json"
    ms1_dir.mkdir(parents=True)
    ms2_dir.mkdir(parents=True)
    (ms1_dir / "spectrum0.js").write_text(
        'spectrum = {"id": 1, "scan": 1, "retention_time": 12.0, '
        '"peaks": [{"mz": 100.0, "intensity": 10.0}, {"mz": 200.0, "intensity": 30.0}]};',
        encoding="utf-8",
    )
    (ms2_dir / "spectrum0.js").write_text(
        'spectrum = {"id": 2, "scan": 2, "retention_time": 18.0, '
        '"target_mz": 500.2, "min_mz": 499.7, "max_mz": 500.7, '
        '"peaks": [{"mz": 150.0, "intensity": 15.0}, {"mz": 250.0, "intensity": 25.0}]};',
        encoding="utf-8",
    )

    profile = inspect_source(source)
    target = tmp_path / "topfd.zp"
    result = convert_source_to_zp(
        source,
        target,
        format_version=3,
        options=ConversionOptions(
            temporary_directory=tmp_path / "work",
            v3_array_compression="raw",
        ),
    )
    deep = validate_zp(target, mode="deep", certificate_path=tmp_path / "deep.json")
    reader = open_zp(target)
    spectra = list(reader.read_spectra())
    precursors = list(reader.read_precursors())
    spectrum, mz_array, intensity_array = reader.read_spectrum_arrays(spectra[-1].spectrum_id)

    assert profile.source_type == "real_topfd_js_bundle"
    assert [profile.relative_label(path) for path in profile.identity_files] == [
        "topfd/ms1_json/spectrum0.js",
        "topfd/ms2_json/spectrum0.js",
    ]
    assert result.plan.required_steps == (
        "file_validate",
        "hash_input",
        "real_topfd_js_parse",
        "string_pool_build",
        "index_build",
        "zp_write",
        "zp_validate",
    )
    assert result.validation.valid is True
    assert deep.valid is True
    assert spectra[0].scan_number == 1
    assert spectrum.scan_number == 2
    assert spectrum.ms_level == 2
    assert [float(value) for value in mz_array.values] == [150.0, 250.0]
    assert [float(value) for value in intensity_array.values] == [15.0, 25.0]
    assert len(precursors) == 1
    assert precursors[0].isolation_lower_mz == 499.7
    assert precursors[0].isolation_upper_mz == 500.7
