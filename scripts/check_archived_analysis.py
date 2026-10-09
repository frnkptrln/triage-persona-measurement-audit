"""Recompute the archived audit in a temporary directory without replacing evidence."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TABLES = (
    "model_outcomes.csv",
    "persona_contrasts.csv",
    "response_format.csv",
    "order_associated_variation.csv",
    "schema_failures.csv",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compare_table(expected_path: Path, actual_path: Path) -> int:
    with expected_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        fields, expected = reader.fieldnames, list(reader)
    with actual_path.open(newline="") as stream:
        reader = csv.DictReader(stream)
        actual_fields, actual = reader.fieldnames, list(reader)
    if fields != actual_fields or len(expected) != len(actual):
        raise ValueError(f"{expected_path.name}: table shape differs")
    for index, (left, right) in enumerate(zip(expected, actual, strict=True), start=2):
        for field in fields:
            a, b = left[field], right[field]
            try:
                x, y = float(a), float(b)
            except (ValueError, TypeError):
                equal = a == b
            else:
                equal = math.isfinite(x) and math.isfinite(y) and math.isclose(x, y, rel_tol=1e-12, abs_tol=1e-12)
            if not equal:
                raise ValueError(f"{expected_path.name}:{index}:{field}: archived={a!r}, recomputed={b!r}")
    return len(expected)


def check_archive(results: Path) -> dict:
    manifest_path = results / "derived/analysis_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    script = ROOT / "scripts/analyze_multimodel.py"
    if sha256(script) != manifest["analysis_script_sha256"]:
        raise ValueError("analysis script differs from the archived provenance manifest")
    reference_spec = json.loads((ROOT / "spec.json").read_text())

    def measurement(spec):
        return {key: value for key, value in spec.items() if key not in {"model", "model_default", "extension"}}

    spec = importlib.util.spec_from_file_location("archived_multimodel_analysis", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected_names = {filename for _, filename, _ in module.RUNS}
    if set(manifest["raw_artifacts"]) != expected_names:
        raise ValueError("raw artifact manifest does not describe exactly the four archived runs")
    records = 0
    for filename in sorted(expected_names):
        path = results / "raw" / filename
        expected = manifest["raw_artifacts"][filename]
        if sha256(path) != expected["sha256"]:
            raise ValueError(f"{filename}: raw artifact hash mismatch")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
        if len(payload["records"]) != expected["records"]:
            raise ValueError(f"{filename}: raw record count mismatch")
        if payload["run_manifest"]["model"] != expected["model"]:
            raise ValueError(f"{filename}: model provenance mismatch")
        if payload["spec"]["model"] != expected["model"]:
            raise ValueError(f"{filename}: instrument model differs from the run manifest")
        if measurement(payload["spec"]) != measurement(reference_spec):
            raise ValueError(f"{filename}: frozen measurement fields changed")
        records += len(payload["records"])

    with tempfile.TemporaryDirectory(prefix="triage-archive-check-") as directory:
        module.RAW = results / "raw"
        module.DERIVED = Path(directory)
        module.main()  # unchanged analysis, including a real figure render
        tables = {name: compare_table(results / "derived" / name, Path(directory) / name) for name in TABLES}
        regenerated_manifest = json.loads((Path(directory) / "analysis_manifest.json").read_text())
        if regenerated_manifest != manifest:
            raise ValueError("recomputed provenance manifest differs from the archived manifest")
    return {
        "status": "pass",
        "raw_runs": len(expected_names),
        "records": records,
        "tables_checked": tables,
        "figure": "rendered in temporary directory; pixels not compared",
        "measurement_contract": "frozen task fields checked; declared model and extension metadata may differ",
        "manifest_sha256": sha256(manifest_path),
        "claim_boundary": "Reanalysis of archived completions; no new model calls, clinical claims or population inference.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=ROOT / "results")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(check_archive(args.results_dir), indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as error:
        print(f"archived analysis check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
