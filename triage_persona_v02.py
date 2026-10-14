"""Offline request planner and raw-completion auditor for the proposed v0.2 pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from run_model import first_braced_object
from triage_persona_instrument import canonical_choice, iter_pairs, load_json

ROOT = Path(__file__).resolve().parent
DEFAULT_SPEC = ROOT / "extensions/2026-10-14/spec-v0.2.json"
SEED_SUPPORT = ("unknown", "unsupported", "documented", "verified")


def schema_for(choices: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["choice", "confidence"],
        "additionalProperties": False,
        "properties": {
            "choice": {"type": "string", "enum": choices},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        },
    }


def validate_spec(spec: dict[str, Any], source_path: Path = ROOT / "spec.json") -> None:
    source = load_json(source_path)
    if spec.get("source", {}).get("frozen_spec_sha256") != hashlib.sha256(source_path.read_bytes()).hexdigest():
        raise ValueError("frozen v0.1 spec hash mismatch")
    if spec.get("status") != "proposed-needs-Frank" or spec.get("created_before_model_calls") is not True:
        raise ValueError("this tool requires the proposed, not-yet-run v0.2 spec")
    if spec.get("instrument_id") != "triage-persona-v0.2-proposal-20261014":
        raise ValueError("unexpected proposed instrument id")
    for field in ("conditions", "triads", "decoding"):
        if spec.get(field) != source[field]:
            raise ValueError(f"{field} differs from this extension's declared scope")
    if spec.get("counterbalancing", {}).get("orientations_per_block") != ["canonical", "reversed"]:
        raise ValueError("every block requires both orientations")
    formats = spec.get("formats")
    if not isinstance(formats, list) or len(formats) != 2:
        raise ValueError("exactly two response formats required")
    for fmt, old in zip(formats, source["formats"]):
        if fmt.get("id") != old["id"] or fmt.get("allowed_choices") != old["allowed_choices"]:
            raise ValueError("formats must retain the frozen response sets")
        if fmt.get("response_schema") != schema_for(fmt["allowed_choices"]):
            raise ValueError("response schema does not match allowed labels and confidence bounds")
        instruction = fmt.get("instruction")
        if not isinstance(instruction, str) or not instruction or any(x in instruction for x in ('{', '}', '|')):
            raise ValueError("prompt instructions must omit literal JSON/enum response examples")
    if set(spec.get("profiles", {})) != set(source["profiles"]):
        raise ValueError("profiles differ from the declared scope")
    n_pairs = len(list(iter_pairs(spec)))
    for name, profile in spec["profiles"].items():
        old = source["profiles"][name]
        if profile.get("condition_ids") != old["condition_ids"] or profile.get("replicates") != old["replicates"]:
            raise ValueError(f"profile {name} changed its conditions or replicates")
        count = len(profile["condition_ids"]) * len(formats) * profile["replicates"] * n_pairs * 2
        if profile.get("expected_records") != count:
            raise ValueError(f"profile {name} expected_records should be {count}")


def block_seed(spec: dict[str, Any], *parts: object) -> int:
    material = "|".join([spec["instrument_id"], *(str(part) for part in parts)]).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big") % (2**63 - 1)


def build_plan(
    spec: dict[str, Any],
    model_id: str,
    model_revision: str,
    profile: str = "pilot",
    seed_support: str = "unknown",
    seed_evidence: str = "",
) -> dict[str, Any]:
    validate_spec(spec)
    if not model_id or "|" in model_id or "::" in model_id:
        raise ValueError("provide a nonempty model id without seed/id delimiters")
    if not re.fullmatch(r"[0-9a-f]{40}", model_revision):
        raise ValueError("model_revision must be an immutable 40-character lowercase commit SHA")
    if seed_support not in SEED_SUPPORT:
        raise ValueError("unknown seed support category")
    if seed_support in {"documented", "verified"} and not seed_evidence.strip():
        raise ValueError("documented or verified seed support requires adapter-specific evidence")
    if profile not in spec["profiles"]:
        raise ValueError("unknown profile")
    selected = spec["profiles"][profile]
    conditions = {condition["id"]: condition for condition in spec["conditions"]}
    spec_hash = hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    blocks: list[list[dict[str, Any]]] = []
    for condition_id in selected["condition_ids"]:
        condition = conditions[condition_id]
        for fmt in spec["formats"]:
            for replicate in range(selected["replicates"]):
                for triad, pair in iter_pairs(spec):
                    parts = [model_id, model_revision, condition_id, fmt["id"], replicate, pair["id"]]
                    seed = block_seed(spec, *parts)
                    block_id = "::".join([spec["instrument_id"], *(str(p) for p in parts)])
                    block = []
                    for reverse in (False, True):
                        a, b = pair["option_a"], pair["option_b"]
                        display_a, display_b = (b, a) if reverse else (a, b)
                        prompt = "\n\n".join([
                            "This is a synthetic resource-triage comparison for research. There is no hidden correct answer.",
                            f"CONTEXT:\n{triad['context']}",
                            f"A. {triad['options'][display_a]}\nB. {triad['options'][display_b]}",
                            fmt["instruction"],
                        ])
                        block.append({
                            "record_id": block_id + ("::reversed" if reverse else "::canonical"),
                            "block_id": block_id,
                            "instrument_id": spec["instrument_id"],
                            "spec_sha256": spec_hash,
                            "model_id": model_id,
                            "model_revision": model_revision,
                            "condition_id": condition_id,
                            "condition_type": condition["type"],
                            "format_id": fmt["id"],
                            "triad_id": triad["id"],
                            "pair_id": pair["id"],
                            "replicate": replicate,
                            "seed": seed,
                            "seed_support": seed_support,
                            "seed_evidence": seed_evidence,
                            "stage": "smoke" if condition_id in {"neutral_canonical", "neutral_paraphrase"}
                            and replicate < 2 else "after_smoke",
                            "display_reversed": reverse,
                            "canonical_option_a": a,
                            "canonical_option_b": b,
                            "display_option_a": display_a,
                            "display_option_b": display_b,
                            "allowed_choices": fmt["allowed_choices"],
                            "response_schema": fmt["response_schema"],
                            "decoding": spec["decoding"],
                            "messages": [{"role": "system", "content": condition["system_prompt"]},
                                         {"role": "user", "content": prompt}],
                        })
                    if replicate % 2:
                        block.reverse()
                    blocks.append(block)
    rng = random.Random(block_seed(spec, model_id, model_revision, profile, "schedule"))
    smoke = [block for block in blocks if block[0]["stage"] == "smoke"]
    remaining = [block for block in blocks if block[0]["stage"] != "smoke"]
    rng.shuffle(smoke)
    rng.shuffle(remaining)
    records = [record for block in smoke + remaining for record in block]
    for index, record in enumerate(records):
        record["call_index"] = index
    assert len(records) == selected["expected_records"]
    return {
        "instrument_id": spec["instrument_id"], "status": spec["status"],
        "spec_sha256": spec_hash, "model_id": model_id, "model_revision": model_revision,
        "profile": profile, "seed_support": seed_support, "seed_evidence": seed_evidence,
        "model_calls_performed": 0, "planned_calls": len(records),
        "smoke_calls": sum(r["stage"] == "smoke" for r in records),
        "after_smoke_calls": sum(r["stage"] != "smoke" for r in records),
        "requested_seed_pairing": True,
        "seed_support_verified_by_planner": False,
        "records": records,
    }


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def parse_output(raw: str, allowed: list[str]) -> dict[str, Any]:
    candidates = [("direct_json", raw.strip())]
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw.strip(), flags=re.DOTALL)
    if fence:
        candidates.append(("outer_code_fence", fence.group(1).strip()))
    braced = first_braced_object(raw)
    if braced is not None:
        candidates.append(("first_braced_object", braced))
    seen = set()
    for route, candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            response = json.loads(candidate, object_pairs_hook=strict_object, parse_constant=reject_constant)
        except (ValueError, TypeError):
            continue
        if not isinstance(response, dict):
            continue
        errors = []
        if set(response) != {"choice", "confidence"}:
            errors.append("expected exactly choice and confidence keys")
        if not isinstance(response.get("choice"), str) or response["choice"] not in allowed:
            errors.append("choice is not one permitted label")
        confidence = response.get("confidence")
        if type(confidence) is not int or not 0 <= confidence <= 100:
            errors.append("confidence must be an integer from 0 to 100")
        return {"response": response, "parser_route": route, "valid": not errors, "errors": errors}
    return {"response": None, "parser_route": None, "valid": False,
            "errors": ["no JSON object under the declared parser policy"]}


def audit_completions(plan: dict[str, Any], completions: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {record["record_id"]: record for record in plan["records"]}
    observed: dict[str, dict[str, Any]] = {}
    rows = []
    blocks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for completion in completions:
        record_id = completion.get("record_id")
        if not isinstance(record_id, str) or record_id not in expected or record_id in observed:
            raise ValueError("unknown or duplicate completion record_id")
        if not isinstance(completion.get("raw_output"), str):
            raise ValueError("every completion must retain a raw_output string")
        extra = set(completion) - {"record_id", "raw_output", "seed_effective", "called_at_utc"}
        if extra:
            raise ValueError(f"unexpected completion fields: {sorted(extra)}")
        effective = completion.get("seed_effective")
        if effective is not None and (type(effective) is not int or not 0 <= effective < 2**63 - 1):
            raise ValueError("seed_effective must be an integer in seed range or null")
        request = expected[record_id]
        row = {**request, **completion, **parse_output(completion["raw_output"], request["allowed_choices"])}
        row["seed_matches_requested"] = effective == request["seed"]
        if row["valid"]:
            row["canonical_choice"] = canonical_choice(request, row["response"]["choice"])
        observed[record_id] = row
        rows.append(row)
        blocks[row["block_id"]].append(row)
    rows.sort(key=lambda row: row["call_index"])
    smoke = [row for row in rows if row["stage"] == "smoke"]
    smoke_complete = len(smoke) == plan["smoke_calls"]
    smoke_invalid = sum(not row["valid"] for row in smoke)
    smoke_stop = smoke_invalid * 10 > len(smoke) if smoke_complete else None
    after_count = sum(row["stage"] != "smoke" for row in rows)
    if after_count and (not smoke_complete or smoke_stop):
        raise ValueError("after-smoke completions violate the complete-smoke/invalid-output gate")
    pairs = Counter()
    for group in blocks.values():
        if len(group) != 2:
            pairs["incomplete"] += 1
        elif not all(row["valid"] for row in group):
            pairs["complete_with_invalid"] += 1
        else:
            pairs["complete_valid"] += 1
            choices = [row["canonical_choice"] for row in group]
            if all(choice in {"A", "B"} for choice in choices):
                pairs["directional_agree" if choices[0] == choices[1] else "directional_disagree"] += 1
            else:
                pairs["nondirectional"] += 1
    all_complete = len(rows) == plan["planned_calls"]
    seed_eligible = bool(rows) and plan["seed_support"] == "verified" and bool(plan["seed_evidence"].strip())
    seed_eligible = seed_eligible and all(row["seed_matches_requested"] for row in rows)
    return {
        "status": "completion-audit", "instrument_id": plan["instrument_id"],
        "planned_calls": plan["planned_calls"], "observed_calls": len(rows),
        "missing_calls": plan["planned_calls"] - len(rows), "all_planned_calls_observed": all_complete,
        "valid_outputs": sum(row["valid"] for row in rows), "invalid_outputs": sum(not row["valid"] for row in rows),
        "smoke_complete": smoke_complete, "smoke_invalid": smoke_invalid, "stop_after_smoke": smoke_stop,
        "seed_support": plan["seed_support"], "seed_evidence": plan["seed_evidence"],
        "seed_matching_eligible_under_declared_evidence": seed_eligible,
        "seed_support_verified_by_auditor": False,
        "blocks": dict(pairs), "unobserved_blocks": len(expected) // 2 - len(blocks),
        "records": rows,
    }


def check_output_paths(outputs: list[Path | None], inputs: list[Path]) -> None:
    """Reject aliases and existing destinations before any output is written."""
    targets = [path for path in outputs if path is not None]
    resolved = [path.resolve() for path in targets]
    if len(set(resolved)) != len(resolved):
        raise ValueError("output paths must be distinct")
    source_paths = {path.resolve() for path in inputs}
    for path, target in zip(targets, resolved):
        if target in source_paths:
            raise ValueError("output path aliases an input")
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"output destination already exists: {path}")


def write_new_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation also refuses a destination created after preflight.
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "plan", "audit"))
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--model-id")
    parser.add_argument("--model-revision")
    parser.add_argument("--profile", choices=("smoke", "pilot", "full"), default="pilot")
    parser.add_argument("--seed-support", choices=SEED_SUPPORT, default="unknown")
    parser.add_argument("--seed-evidence", default="")
    parser.add_argument("--requests", type=Path)
    parser.add_argument("--completions", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    spec = load_json(args.spec)
    validate_spec(spec)
    if args.command == "validate":
        print(json.dumps({"status": "valid-proposal", "model_calls_performed": 0}))
        return
    if not args.model_id or not args.model_revision:
        parser.error("--model-id and --model-revision are required")
    plan = build_plan(spec, args.model_id, args.model_revision, args.profile, args.seed_support, args.seed_evidence)
    if args.command == "plan":
        check_output_paths([args.requests, args.output], [args.spec, ROOT / "spec.json"])
        if args.requests:
            write_new_text(args.requests, "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in plan["records"]
            ))
        output = {key: value for key, value in plan.items() if key != "records"}
    else:
        if not args.completions:
            parser.error("audit requires --completions")
        check_output_paths([args.output], [args.spec, ROOT / "spec.json", args.completions])
        with args.completions.open(encoding="utf-8") as handle:
            completions = [json.loads(line, object_pairs_hook=strict_object, parse_constant=reject_constant)
                           for line in handle if line.strip()]
        if not all(isinstance(row, dict) for row in completions):
            raise ValueError("completion JSONL rows must be objects")
        output = audit_completions(plan, completions)
    rendered = json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if args.output:
        write_new_text(args.output, rendered)
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()

