import copy
import json
import sys
from collections import defaultdict

import pytest

import triage_persona_v02 as v02


@pytest.fixture
def spec():
    return v02.load_json(v02.DEFAULT_SPEC)


@pytest.fixture
def plan(spec):
    return v02.build_plan(spec, "example/model", "1" * 40)


def completion(record, choice="A", confidence=50, **extra):
    return {
        "record_id": record["record_id"],
        "raw_output": json.dumps({"choice": choice, "confidence": confidence}),
        "seed_effective": record["seed"],
        **extra,
    }


def test_pilot_doubles_orientations_without_resampling_smoke(spec, plan):
    smoke_plan = v02.build_plan(spec, "example/model", "1" * 40, "smoke")
    assert (plan["planned_calls"], plan["smoke_calls"], plan["after_smoke_calls"]) == (384, 96, 288)
    assert plan["model_calls_performed"] == 0
    pilot_smoke = {row["record_id"]: row for row in plan["records"] if row["stage"] == "smoke"}
    assert len(pilot_smoke) == 96
    for row in smoke_plan["records"]:
        # Each profile has its own block schedule but identical requests.
        assert {k: v for k, v in row.items() if k != "call_index"} == {
            k: v for k, v in pilot_smoke[row["record_id"]].items() if k != "call_index"
        }
    assert all(row["stage"] == "smoke" for row in plan["records"][:96])


def test_every_block_has_both_orders_same_seed_and_single_change(plan):
    groups = defaultdict(list)
    for row in plan["records"]:
        groups[row["block_id"]].append(row)
    assert len(groups) == 192
    for canonical_and_reversed in groups.values():
        assert len(canonical_and_reversed) == 2
        left, right = canonical_and_reversed
        assert {left["display_reversed"], right["display_reversed"]} == {False, True}
        assert left["seed"] == right["seed"]
        assert left["display_option_a"] == right["display_option_b"]
        assert left["display_option_b"] == right["display_option_a"]
        assert left["messages"][0] == right["messages"][0]
        # Everything around the displayed options remains identical.
        assert left["messages"][1]["content"].split("\n\n")[0:2] == right["messages"][1]["content"].split("\n\n")[0:2]
        assert left["messages"][1]["content"].split("\n\n")[-1] == right["messages"][1]["content"].split("\n\n")[-1]
        assert left["display_reversed"] is bool(left["replicate"] % 2)


def test_seed_depends_on_immutable_revision_and_replicate(spec, plan):
    other = v02.build_plan(spec, "example/model", "2" * 40)
    assert {r["seed"] for r in plan["records"]}.isdisjoint({r["seed"] for r in other["records"]})
    assert len({r["seed"] for r in plan["records"]}) == 192
    assert plan == v02.build_plan(spec, "example/model", "1" * 40)


def test_no_literal_response_examples_and_schema_exactly_matches(spec, plan):
    for fmt in spec["formats"]:
        assert fmt["response_schema"] == v02.schema_for(fmt["allowed_choices"])
    for row in plan["records"]:
        assert '"choice":' not in row["messages"][1]["content"]
        assert "A|B" not in row["messages"][1]["content"]
    invalid = copy.deepcopy(spec)
    invalid["formats"][0]["instruction"] += ' {"choice":"A","confidence":50}'
    with pytest.raises(ValueError, match="omit literal"):
        v02.validate_spec(invalid)


@pytest.mark.parametrize("bad", ["main", "", "A" * 40, "1" * 39])
def test_pinned_revision_required(spec, bad):
    with pytest.raises(ValueError, match="immutable"):
        v02.build_plan(spec, "model", bad)


def test_undeclared_instrument_changes_rejected(spec):
    for key in ("triads", "conditions", "decoding"):
        altered = copy.deepcopy(spec)
        altered[key] = {}
        with pytest.raises(ValueError, match="declared scope"):
            v02.validate_spec(altered)


@pytest.mark.parametrize("raw", [
    '{"choice":"A|B|refuse","confidence":50}',
    '{"choice":"A","confidence":true}',
    '{"choice":"A","confidence":50.0}',
    '{"choice":"A","confidence":101}',
    '{"choice":"A","confidence":50,"explanation":"x"}',
    '{"choice":"A","choice":"B","confidence":50}',
    '{"choice":"A","confidence":NaN}',
    '{"choice":["A"],"confidence":50}',
    "I choose A",
])
def test_invalid_outputs_are_not_repaired(raw):
    parsed = v02.parse_output(raw, ["A", "B", "refuse"])
    assert parsed["valid"] is False


@pytest.mark.parametrize("raw,route", [
    ('{"choice":"A","confidence":50}', "direct_json"),
    ('```json\n{"choice":"A","confidence":50}\n```', "outer_code_fence"),
    ('Answer: {"choice":"A","confidence":50}', "first_braced_object"),
])
def test_declared_parser_routes(raw, route):
    assert v02.parse_output(raw, ["A", "B", "refuse"])["parser_route"] == route


def test_audit_canonicalizes_and_preserves_invalid_raw(plan):
    # Entire smoke must be observed before any after-smoke output.
    records = plan["records"][:96]
    outputs = [completion(row, "B" if row["display_reversed"] else "A") for row in records]
    outputs[0]["raw_output"] = '{"choice":"A|B|refuse","confidence":50}'
    audit = v02.audit_completions(plan, outputs)
    assert audit["invalid_outputs"] == 1
    assert audit["records"][0]["raw_output"] == outputs[0]["raw_output"]
    assert audit["records"][0]["response"]["choice"] == "A|B|refuse"
    assert audit["blocks"] == {"complete_with_invalid": 1, "complete_valid": 47, "directional_agree": 47}
    assert audit["stop_after_smoke"] is False
    assert audit["seed_matching_eligible_under_declared_evidence"] is False


def test_smoke_gate_and_missing_outputs(plan):
    outputs = [completion(row) for row in plan["records"][:96]]
    for row in outputs[:10]:
        row["raw_output"] = "invalid"
    assert v02.audit_completions(plan, outputs)["stop_after_smoke"] is True
    outputs.append(completion(plan["records"][96]))
    with pytest.raises(ValueError, match="gate"):
        v02.audit_completions(plan, outputs)
    incomplete = v02.audit_completions(plan, outputs[:1])
    assert incomplete["stop_after_smoke"] is None
    assert incomplete["blocks"]["incomplete"] == 1
    assert incomplete["missing_calls"] == 383


def test_only_declared_verified_seed_support_is_eligible(spec):
    with pytest.raises(ValueError, match="evidence"):
        v02.build_plan(spec, "example/model", "1" * 40, seed_support="verified")
    plan = v02.build_plan(spec, "example/model", "1" * 40, seed_support="verified",
                          seed_evidence="local adapter test and runtime manifest at immutable commit")
    outputs = [completion(row) for row in plan["records"][:96]]
    report = v02.audit_completions(plan, outputs)
    assert report["seed_matching_eligible_under_declared_evidence"] is True
    assert report["seed_support_verified_by_auditor"] is False
    outputs[0]["seed_effective"] = None
    assert v02.audit_completions(plan, outputs)["seed_matching_eligible_under_declared_evidence"] is False


def test_duplicate_unknown_and_changed_seed_completion_rejected(plan):
    row = completion(plan["records"][0])
    with pytest.raises(ValueError, match="duplicate"):
        v02.audit_completions(plan, [row, row])
    with pytest.raises(ValueError, match="unknown"):
        v02.audit_completions(plan, [{**row, "record_id": "unknown"}])
    with pytest.raises(ValueError, match="unexpected"):
        v02.audit_completions(plan, [{**row, "seed": 3}])
    with pytest.raises(ValueError, match="seed_effective"):
        v02.audit_completions(plan, [{**row, "seed_effective": True}])


def test_full_pilot_audit_reports_complete(plan):
    outputs = [completion(row) for row in plan["records"]]
    report = v02.audit_completions(plan, outputs)
    assert report["observed_calls"] == 384
    assert report["all_planned_calls_observed"] is True
    assert report["blocks"]["directional_disagree"] == 192
    assert report["invalid_outputs"] == 0


def cli_args(command, *extra):
    return ["triage_persona_v02.py", command, "--model-id", "example/model",
            "--model-revision", "1" * 40, "--profile", "smoke", *map(str, extra)]


def test_cli_audit_refuses_to_overwrite_raw_completions(tmp_path, monkeypatch):
    raw = tmp_path / "raw.jsonl"
    original = b'{"record_id":"untrusted","raw_output":"invalid"}\n'
    raw.write_bytes(original)
    monkeypatch.setattr(sys, "argv", cli_args("audit", "--completions", raw, "--output", raw))
    with pytest.raises(ValueError, match="aliases an input"):
        v02.main()
    assert raw.read_bytes() == original


def test_cli_plan_refuses_request_summary_alias_before_writes(tmp_path, monkeypatch):
    output = tmp_path / "requests.jsonl"
    alias = tmp_path / "subdir" / ".." / "requests.jsonl"
    monkeypatch.setattr(sys, "argv", cli_args("plan", "--requests", output, "--output", alias))
    with pytest.raises(ValueError, match="distinct"):
        v02.main()
    assert not output.exists()


def test_cli_preflights_all_outputs_before_creating_requests(tmp_path, monkeypatch):
    requests = tmp_path / "requests.jsonl"
    summary = tmp_path / "summary.json"
    summary.write_bytes(b"existing evidence\n")
    monkeypatch.setattr(sys, "argv", cli_args("plan", "--requests", requests, "--output", summary))
    with pytest.raises(FileExistsError):
        v02.main()
    assert not requests.exists()
    assert summary.read_bytes() == b"existing evidence\n"


def test_cli_audit_refuses_symlink_to_raw_input(tmp_path, monkeypatch):
    raw = tmp_path / "raw.jsonl"
    raw.write_bytes(b"original raw evidence\n")
    alias = tmp_path / "alias.json"
    alias.symlink_to(raw)
    monkeypatch.setattr(sys, "argv", cli_args("audit", "--completions", raw, "--output", alias))
    with pytest.raises(ValueError, match="aliases an input"):
        v02.main()
    assert raw.read_bytes() == b"original raw evidence\n"


def test_exclusive_output_write_refuses_late_collision(tmp_path):
    output = tmp_path / "new.json"
    v02.check_output_paths([output], [])
    output.write_bytes(b"created by another process\n")
    with pytest.raises(FileExistsError):
        v02.write_new_text(output, "replacement")
    assert output.read_bytes() == b"created by another process\n"


def test_cli_fresh_plan_and_audit_preserve_raw_bytes(tmp_path, monkeypatch, spec):
    requests, summary = tmp_path / "requests.jsonl", tmp_path / "summary.json"
    monkeypatch.setattr(sys, "argv", cli_args("plan", "--requests", requests, "--output", summary))
    v02.main()
    rows = [json.loads(line) for line in requests.read_text().splitlines()]
    assert len(rows) == json.loads(summary.read_text())["planned_calls"] == 96
    raw = tmp_path / "raw.jsonl"
    raw.write_text("".join(json.dumps(completion(row)) + "\n" for row in rows))
    original = raw.read_bytes()
    audit = tmp_path / "audit.json"
    monkeypatch.setattr(sys, "argv", cli_args("audit", "--completions", raw, "--output", audit))
    v02.main()
    assert raw.read_bytes() == original
    report = json.loads(audit.read_text())
    assert report["observed_calls"] == 96
    assert report["all_planned_calls_observed"] is True
    assert report["seed_support_verified_by_auditor"] is False

