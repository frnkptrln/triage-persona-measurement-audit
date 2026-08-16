import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("triage_persona_instrument", ROOT / "triage_persona_instrument.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_spec_and_profiles():
    spec = MODULE.load_json(ROOT / "spec.json")
    MODULE.validate_spec(spec)
    for profile in ("smoke", "pilot", "full"):
        records = MODULE.build_records(spec, profile, "test/model")
        assert len(records) == spec["profiles"][profile]["expected_records"]
        assert len({record["record_id"] for record in records}) == len(records)


def test_counterbalancing_and_canonicalization():
    spec = MODULE.load_json(ROOT / "spec.json")
    records = MODULE.build_records(spec, "smoke", "test/model")
    even = next(record for record in records if record["replicate"] == 0)
    odd = next(
        record
        for record in records
        if record["replicate"] == 1
        and record["condition_id"] == even["condition_id"]
        and record["format_id"] == even["format_id"]
        and record["pair_id"] == even["pair_id"]
    )
    assert not even["display_reversed"]
    assert odd["display_reversed"]
    assert MODULE.canonical_choice(even, "A") == "A"
    assert MODULE.canonical_choice(odd, "A") == "B"


def test_synthetic_summary_has_wording_contrast():
    spec = MODULE.load_json(ROOT / "spec.json")
    records = MODULE.build_records(spec, "smoke", "test/model")
    for record in records:
        record["response"] = {"choice": "A", "confidence": 80}
    summary = MODULE.summarize(spec, records)
    assert not summary["errors"]
    assert len(summary["planned_contrasts"]) == 2
    assert all(row["mean_itemwise_absolute_a_rate_shift"] == 0 for row in summary["planned_contrasts"])
    assert all(row["mean_itemwise_absolute_a_rate_order_shift"] == 1 for row in summary["order_sensitivity"])


def test_pilot_persona_contrasts_report_excess_over_wording_floor():
    spec = MODULE.load_json(ROOT / "spec.json")
    records = MODULE.build_records(spec, "pilot", "test/model")
    for record in records:
        record["response"] = {"choice": "A", "confidence": 80}
    summary = MODULE.summarize(spec, records)
    persona = [row for row in summary["planned_contrasts"] if row["target_type"] == "persona_stress_test"]
    assert len(summary["planned_contrasts"]) == 6
    assert len(persona) == 4
    assert all(row["wording_floor"] == 0 for row in persona)
    assert all(row["excess_shift_over_wording_floor"] == 0 for row in persona)
