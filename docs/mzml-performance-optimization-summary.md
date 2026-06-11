# mzML / BU Chart Performance Optimization Summary

## Background

Viewer originally loaded every mzML spectrum into a dataset-level resident
bundle before returning lightweight metadata or a single chart. A cold request
could therefore parse every run, convert every peak array to Python lists, and
retain the complete dataset in memory.

The optimization project separates metadata, derived overview data, scan
location metadata, and individual spectrum access. Normal chart requests no
longer use dataset-wide mzML residency.

## Original Bottlenecks

- Dataset detail triggered full mzML parsing before returning metadata.
- Concurrent chart requests competed for the same long global loading lock.
- A request for one spectrum loaded every spectrum in every dataset run.
- BU MS1/MS2 and XIC requests traversed complete runs.
- TIC/BPC was calculated from all MS1 peak arrays during each GET request.
- RT-m/z heatmaps returned all match points to Python for binning.
- Missing derived files were difficult to diagnose in the frontend.

## Optimization Goals

- Keep dataset detail independent from spectrum loading.
- Read a known indexed mzML scan without building a full scan map.
- Use small run-level metadata indexes to locate scans by RT and isolation
  window.
- Precompute stable overview chromatograms.
- Aggregate RT-m/z cells in PostgreSQL.
- Keep chart failures local and actionable.
- Preserve existing API response schemas and chart semantics.

## Completed Changes

### 1. Dataset detail no longer preloads mzML

`GET /api/v1/datasets/{slug}` returns metadata, analysis mode, cutoffs, and BU
run summaries without calling the spectrum residency loader.

### 2. mzML dataset residency single-flight

The legacy residency path now uses dataset-level single-flight coordination.
The global lock protects state transitions only; different datasets may load
concurrently. This path remains available for features that have not migrated,
but it is no longer part of the optimized chart requests.

### 3. Indexed mzML spectrum reader

`back/app/services/mzml_scan_reader.py` uses the embedded indexed mzML offsets
and `PreIndexedMzML.get_by_id()` to read a known scan. It caches only the
`scan_number -> native_id` mapping and converts only the requested spectrum's
peak arrays for the response.

### 4. mzML scan index

`back/app/services/mzml_scan_index.py` stores lightweight run metadata:

- scan number and native ID
- MS level and retention time in minutes
- TIC and BPC
- precursor m/z
- isolation target and absolute lower/upper m/z boundaries

The index does not store complete m/z or intensity arrays. It supports scan,
RT, MS-level, TIC, and isolation-window queries.

### 5. BU MS1 / MS2 spectrum optimization

BU MS1 selection uses the scan index with the existing priority order:

1. highest TIC
2. nearest RT
3. lowest scan number

BU MS2 uses the direct indexed reader when a positive scan is known. Matches
without a positive scan use the lightweight index to locate an MS2 candidate,
then read only that spectrum.

### 6. BU TIC/BPC chromatogram summary

TIC/BPC summaries are generated explicitly and read directly by normal GET
requests. Missing or stale summaries return HTTP 409 and are never rebuilt
inside a chart request.

### 7. BU RT-m/z database binning

PostgreSQL performs `width_bucket` aggregation after applying the existing
dataset, run, query, and decoy filters. Python receives at most 80 x 80
non-empty cells instead of all match points.

### 8. Precursor XIC optimization

The scan index selects MS1 scans in the existing RT window. A request-scoped
indexed reader reads each candidate scan once. M, M+1, and M+2 traces retain
the existing ppm-window maximum-intensity semantics.

### 9. Product XIC optimization

The scan index selects MS2 scans by RT and isolation window. Each candidate
spectrum is read once, and all selected product ions are evaluated together
using the existing ppm-window maximum-intensity semantics.

### 10. Unified derived data backfill

`back/app/services/derived_data_backfill.py` and
`back/scripts/backfill_dataset_derived_data.py` generate and validate:

- scan indexes for every mzML run
- chromatogram summaries for BOTTOM_UP mzML runs

Ready files are skipped by default. Missing or stale files are generated.
`--force` rebuilds ready data, while `--check-only` performs no writes.

### 11. Frontend chart loading and error states

`front/src/lib/apiError.ts` classifies API failures, and
`front/src/components/common/plot-status.tsx` renders local loading, empty,
unsupported, derived-data missing/stale, and generic error states. HTTP
404/409/422 chart failures are not retried indefinitely.

### 12. Import flow derived data integration

The main `POST /api/v1/imports` workflow remains asynchronous. After the final
dataset/run/path transaction commits, its background worker directly calls the
derived-data service. It does not invoke a subprocess.

Derived-data errors do not roll back an imported dataset. Other runs continue,
the import job finishes with a warning, and the job detail includes the manual
recovery command. Direct legacy adapter CLIs retain their previous behavior.

No ordinary spectrum or chromatogram API implicitly generates derived data.

## Derived Data Files

Files are stored below the configured Viewer data root:

```text
.viewer-derived/mzml-scan-index/{dataset_id}/{run_id}/
  scan-index-v1.npz
  scan-index-v1.json

.viewer-derived/bu-chromatograms/{dataset_id}/{run_id}/
  summary-v1.npz
  summary-v1.json
```

NPZ files are replaced atomically first. JSON metadata is replaced last and is
the commit marker. Both files must exist, and `source_path`, `source_size`, and
`source_mtime_ns` must match the source mzML.

## Commands

Run commands from `back/`:

```bash
python scripts/backfill_dataset_derived_data.py --dataset-id <id>
python scripts/backfill_dataset_derived_data.py --slug <slug>
python scripts/backfill_dataset_derived_data.py --dataset-id <id> --run-id <run_id>
python scripts/backfill_dataset_derived_data.py --slug <slug> --check-only
python scripts/backfill_dataset_derived_data.py --slug <slug> --force
```

The explicit command remains the recovery and maintenance entry point even
though the main API import now builds derived data automatically.

## Expected Performance

Recorded BU smoke-test results:

| Request | Time | Returned points |
| --- | ---: | ---: |
| TIC | 70.3 ms | 5,778 |
| BPC | 3.5 ms | 5,778 |
| MS1 | 437.1 ms | one spectrum |
| MS2 | 291.9 ms | one spectrum |
| Precursor XIC | 1,215.4 ms | 406 |
| Product XIC | 550.9 ms | 135 |

Recorded derived-data results:

| Item | Result |
| --- | ---: |
| Scan index NPZ | 2,216,341 bytes |
| Chromatogram NPZ | 98,361 bytes |
| Forced rebuild total | 169.21 s |
| Check-only | 52.7 ms |

The first explicit derived-data generation still streams the source mzML and
therefore takes time. Normal chart requests avoid dataset-wide peak residency
and do not show the previous full-bundle memory increase.

## Error Handling

- `scan_index_missing` / `scan_index_stale`: HTTP 409 with a backfill command.
- `chromatogram_summary_missing` / `chromatogram_summary_stale`: HTTP 409.
- Unsupported raw or indexed mzML formats remain explicit 4xx errors.
- Empty/no-signal chart results are distinct from loading and server errors.
- A failure in one chart does not block the rest of the page.
- A post-import derived-data failure does not roll back the database import.

## Metadata Fingerprint Contract

Dataset duplicate detection remains metadata-only for predictable performance:

```text
relative_path | size | mtime_ns
```

Sorted manifest text is hashed with MD5 and remains a 32-character lowercase
hex value. File contents, including large mzML files, are never read.

Consequently, replacing a file with different content while preserving both
its exact size and exact `mtime_ns` is intentionally not detectable. This is
an accepted tradeoff required by the metadata-only contract and the fingerprint
performance target of 0.5 seconds or less on the benchmark dataset.

The final benchmark scanned 32,998 files in a median 0.1496 seconds while
retaining the metadata-only contract.

## Testing

The project includes focused tests for:

- dataset detail residency separation
- residency single-flight and failure release
- indexed spectrum reads
- scan-index generation, fingerprints, and query helpers
- BU MS1/MS2, precursor XIC, and product XIC paths
- chromatogram summaries and missing/stale behavior
- PostgreSQL RT-m/z binning
- unified and post-import derived-data orchestration
- frontend API error parsing and local chart states
- metadata fingerprint stability and no-content-read behavior

Release verification commands:

```bash
pytest back/tests -q
cd front
npm run lint
npm run build
npm run test:e2e
git diff --check
```

## Remaining Optional Improvements

- Frontend viewport-driven chart loading for very large match pages.
- Import job cancellation and richer per-run derived-data progress.
- A deployment-level process or queue for derived generation when import
  concurrency grows.
- Cross-process single-flight if the deployment moves to multiple workers.
- Additional vendor native-ID adapters when new mzML producers are introduced.
