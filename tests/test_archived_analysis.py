import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_archived_analysis", ROOT / "scripts/check_archived_analysis.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


@pytest.fixture
def results(tmp_path):
    destination = tmp_path / "results"
    shutil.copytree(ROOT / "results", destination)
    return destination


def test_all_archived_tables_reproduce_without_writing_source_evidence(results):
    before = {str(path.relative_to(results)): path.read_bytes() for path in results.rglob("*") if path.is_file()}
    report = checker.check_archive(results)
    assert report["raw_runs"] == 4
    assert report["records"] == 480
    assert len(report["tables_checked"]) == 5
    after = {str(path.relative_to(results)): path.read_bytes() for path in results.rglob("*") if path.is_file()}
    assert before == after


def test_raw_artifact_change_fails_before_reanalysis(results):
    path = results / "raw/qwen3-4b.json.gz"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="hash mismatch"):
        checker.check_archive(results)


def test_table_drift_is_detected(results):
    path = results / "derived/response_format.csv"
    path.write_text(path.read_text().replace("1.0", "0.5", 1))
    with pytest.raises(ValueError, match="response_format"):
        checker.check_archive(results)


def test_extra_raw_manifest_entry_is_not_ignored(results):
    path = results / "derived/analysis_manifest.json"
    data = json.loads(path.read_text())
    data["raw_artifacts"]["unregistered.json.gz"] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="exactly the four"):
        checker.check_archive(results)
