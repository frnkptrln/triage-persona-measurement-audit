"""Validate, export, and summarize the frozen Triage x persona instrument."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
DEFAULT_SPEC = ROOT / "spec.json"


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def unique_ids(items: list[dict[str, Any]], label: str) -> list[str]:
    values = [item.get("id") for item in items]
    if not all(isinstance(value, str) and value for value in values):
        raise ValueError(f"every {label} entry needs a non-empty id")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} ids must be unique")
    return values


def validate_spec(spec: dict[str, Any]) -> None:
    if not spec.get("created_before_model_calls"):
        raise ValueError("created_before_model_calls must be true")
    model = spec.get("model")
    decoding = spec.get("decoding")
    if not isinstance(model, dict) or not model.get("id") or not model.get("revision"):
        raise ValueError("model id and revision must be frozen")
    required_decoding = {
        "do_sample",
        "temperature",
        "top_p",
        "max_new_tokens",
        "repetition_penalty",
        "one_record_per_call",
        "seed_source",
    }
    if not isinstance(decoding, dict) or not required_decoding <= set(decoding):
        raise ValueError("decoding configuration is incomplete")
    if decoding["do_sample"] is not True or decoding["one_record_per_call"] is not True:
        raise ValueError("frozen pilot requires sampled, one-record-per-call decoding")
    if not isinstance(spec.get("parser_policy"), list) or not spec["parser_policy"]:
        raise ValueError("parser policy must be frozen")
    conditions = spec.get("conditions")
    formats = spec.get("formats")
    triads = spec.get("triads")
    if not isinstance(conditions, list) or len(conditions) < 3:
        raise ValueError("conditions must contain a baseline, paraphrase, and stress test")
    if not isinstance(formats, list) or len(formats) != 2:
        raise ValueError("formats must contain exactly two response formats")
    if not isinstance(triads, list) or not triads:
        raise ValueError("triads must be non-empty")
    condition_ids = unique_ids(conditions, "conditions")
    format_ids = unique_ids(formats, "formats")
    unique_ids(triads, "triads")
    if {item["type"] for item in conditions} < {
        "neutral_baseline",
        "neutral_paraphrase_control",
        "persona_stress_test",
    }:
        raise ValueError("condition types are incomplete")
    if set(format_ids) != {"forced_binary", "uncertainty_enabled"}:
        raise ValueError("unexpected response formats")
    pair_ids: list[str] = []
    for triad in triads:
        options = triad.get("options")
        pairs = triad.get("pairs")
        if not isinstance(options, dict) or len(options) != 3:
            raise ValueError(f"triad {triad.get('id')} must define exactly three options")
        if not isinstance(pairs, list) or len(pairs) != 3:
            raise ValueError(f"triad {triad.get('id')} must define exactly three pairs")
        expected_pairs = {frozenset(pair) for pair in __import__("itertools").combinations(options, 2)}
        observed_pairs = set()
        for pair in pairs:
            pair_ids.append(pair.get("id"))
            a, b = pair.get("option_a"), pair.get("option_b")
            if a not in options or b not in options or a == b:
                raise ValueError(f"invalid option reference in {pair.get('id')}")
            observed_pairs.add(frozenset((a, b)))
        if observed_pairs != expected_pairs:
            raise ValueError(f"triad {triad.get('id')} does not cover every option pair")
    if len(pair_ids) != len(set(pair_ids)) or not all(isinstance(x, str) for x in pair_ids):
        raise ValueError("pair ids must be unique strings")
    for fmt in formats:
        allowed = fmt.get("allowed_choices")
        if not isinstance(allowed, list) or not {"A", "B", "refuse"} <= set(allowed):
            raise ValueError(f"format {fmt.get('id')} has invalid choices")
    n_pairs = len(pair_ids)
    for profile_name, profile in spec.get("profiles", {}).items():
        selected = profile.get("condition_ids")
        if not isinstance(selected, list) or not set(selected) <= set(condition_ids):
            raise ValueError(f"profile {profile_name} has invalid conditions")
        reps = profile.get("replicates")
        if not isinstance(reps, int) or reps < 1:
            raise ValueError(f"profile {profile_name} has invalid replicates")
        expected = len(selected) * len(formats) * reps * n_pairs
        if profile.get("expected_records") != expected:
            raise ValueError(f"profile {profile_name} expected_records should be {expected}")


def prompt_seed(spec: dict[str, Any], *parts: object) -> int:
    material = "|".join([spec["instrument_id"], *(str(part) for part in parts)]).encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big")


def iter_pairs(spec: dict[str, Any]):
    for triad in spec["triads"]:
        for pair in triad["pairs"]:
            yield triad, pair


def build_records(spec: dict[str, Any], profile_name: str, model_id: str) -> list[dict[str, Any]]:
    validate_spec(spec)
    profile = spec["profiles"].get(profile_name)
    if profile is None:
        raise ValueError(f"unknown profile {profile_name!r}")
    conditions = {item["id"]: item for item in spec["conditions"]}
    records: list[dict[str, Any]] = []
    for condition_id in profile["condition_ids"]:
        condition = conditions[condition_id]
        for fmt in spec["formats"]:
            for replicate in range(profile["replicates"]):
                reversed_order = bool(spec["counterbalancing"]["reverse_options_on_odd_repetitions"] and replicate % 2)
                for triad, pair in iter_pairs(spec):
                    canonical_a = pair["option_a"]
                    canonical_b = pair["option_b"]
                    display_a = canonical_b if reversed_order else canonical_a
                    display_b = canonical_a if reversed_order else canonical_b
                    record_id = "::".join(
                        [
                            spec["instrument_id"],
                            model_id,
                            condition_id,
                            fmt["id"],
                            f"r{replicate:02d}",
                            pair["id"],
                        ]
                    )
                    user_prompt = "\n\n".join(
                        [
                            "This is a synthetic resource-triage comparison for research. There is no hidden correct answer.",
                            f"CONTEXT:\n{triad['context']}",
                            f"A. {triad['options'][display_a]}\nB. {triad['options'][display_b]}",
                            fmt["instruction"],
                        ]
                    )
                    records.append(
                        {
                            "record_id": record_id,
                            "instrument_id": spec["instrument_id"],
                            "model_id": model_id,
                            "model_revision": (spec["model"]["revision"] if model_id == spec["model"]["id"] else None),
                            "decoding": spec["decoding"],
                            "condition_id": condition_id,
                            "condition_type": condition["type"],
                            "format_id": fmt["id"],
                            "triad_id": triad["id"],
                            "pair_id": pair["id"],
                            "replicate": replicate,
                            "seed": prompt_seed(
                                spec,
                                model_id,
                                condition_id,
                                fmt["id"],
                                replicate,
                                pair["id"],
                            ),
                            "display_reversed": reversed_order,
                            "canonical_option_a": canonical_a,
                            "canonical_option_b": canonical_b,
                            "display_option_a": display_a,
                            "display_option_b": display_b,
                            "allowed_choices": fmt["allowed_choices"],
                            "messages": [
                                {"role": "system", "content": condition["system_prompt"]},
                                {"role": "user", "content": user_prompt},
                            ],
                        }
                    )
    if len(records) != profile["expected_records"]:
        raise AssertionError("generated record count does not match frozen profile")
    return records


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError(f"line {line_number} is not an object")
            records.append(value)
    if not records:
        raise ValueError(f"{path} contains no records")
    return records


def validate_response(record: dict[str, Any]) -> tuple[str, int]:
    response = record.get("response")
    if not isinstance(response, dict):
        raise TypeError("missing structured response")
    choice = response.get("choice")
    if choice not in record["allowed_choices"]:
        raise ValueError(f"choice {choice!r} is not allowed")
    confidence = response.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, int) or not 0 <= confidence <= 100:
        raise ValueError("confidence must be an integer from 0 to 100")
    return choice, confidence


def canonical_choice(record: dict[str, Any], choice: str) -> str:
    if record.get("display_reversed") and choice in {"A", "B"}:
        return "B" if choice == "A" else "A"
    return choice


def summarize(spec: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    validate_spec(spec)
    cells: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "requested": 0,
            "valid": 0,
            "invalid": 0,
            "choices": Counter(),
            "confidences": [],
        }
    )
    item_counts: dict[tuple[str, str, str], Counter] = defaultdict(Counter)
    order_item_counts: dict[tuple[str, str, str, bool], Counter] = defaultdict(Counter)
    trial_choices: dict[tuple[str, str, int, str], dict[str, str]] = defaultdict(dict)
    errors = []
    for line_number, record in enumerate(records, 1):
        cell_key = (record.get("condition_id"), record.get("format_id"))
        cell = cells[cell_key]
        cell["requested"] += 1
        try:
            choice, confidence = validate_response(record)
            choice = canonical_choice(record, choice)
        except (KeyError, TypeError, ValueError) as exc:
            cell["invalid"] += 1
            errors.append({"line": line_number, "record_id": record.get("record_id"), "error": str(exc)})
            continue
        cell["valid"] += 1
        cell["choices"][choice] += 1
        cell["confidences"].append(confidence)
        item_counts[(cell_key[0], cell_key[1], record["pair_id"])][choice] += 1
        order_item_counts[(cell_key[0], cell_key[1], record["pair_id"], bool(record["display_reversed"]))][choice] += 1
        trial_choices[(cell_key[0], cell_key[1], record["replicate"], record["triad_id"])][record["pair_id"]] = choice

    cell_rows = []
    for (condition_id, format_id), cell in sorted(cells.items()):
        ab = cell["choices"]["A"] + cell["choices"]["B"]
        cell_rows.append(
            {
                "condition_id": condition_id,
                "format_id": format_id,
                "requested": cell["requested"],
                "valid": cell["valid"],
                "invalid": cell["invalid"],
                "choice_counts": dict(sorted(cell["choices"].items())),
                "canonical_a_rate_among_ab": cell["choices"]["A"] / ab if ab else None,
                "refusal_rate": cell["choices"]["refuse"] / cell["valid"] if cell["valid"] else None,
                "uncertainty_or_equal_rate": (
                    (cell["choices"]["uncertain"] + cell["choices"]["equal"]) / cell["valid"] if cell["valid"] else None
                ),
                "mean_confidence": (sum(cell["confidences"]) / len(cell["confidences"]) if cell["confidences"] else None),
            }
        )

    condition_types = {item["id"]: item["type"] for item in spec["conditions"]}
    present_conditions = {record.get("condition_id") for record in records}
    contrast_targets = [
        item["id"]
        for item in spec["conditions"]
        if item["id"] in present_conditions and item["type"] in {"neutral_paraphrase_control", "persona_stress_test"}
    ]
    contrasts = []
    for fmt in (item["id"] for item in spec["formats"]):
        for target in contrast_targets:
            shifts = []
            for _, pair in iter_pairs(spec):
                left = item_counts[("neutral_canonical", fmt, pair["id"])]
                right = item_counts[(target, fmt, pair["id"])]
                left_n = left["A"] + left["B"]
                right_n = right["A"] + right["B"]
                if left_n and right_n:
                    shifts.append(abs(left["A"] / left_n - right["A"] / right_n))
            contrasts.append(
                {
                    "format_id": fmt,
                    "baseline": "neutral_canonical",
                    "target": target,
                    "target_type": condition_types[target],
                    "n_items_with_ab_data": len(shifts),
                    "mean_itemwise_absolute_a_rate_shift": sum(shifts) / len(shifts) if shifts else None,
                }
            )
    wording_floors = {
        row["format_id"]: row["mean_itemwise_absolute_a_rate_shift"]
        for row in contrasts
        if row["target_type"] == "neutral_paraphrase_control"
    }
    for row in contrasts:
        floor = wording_floors.get(row["format_id"])
        row["wording_floor"] = floor
        row["excess_shift_over_wording_floor"] = (
            row["mean_itemwise_absolute_a_rate_shift"] - floor
            if row["target_type"] == "persona_stress_test"
            and row["mean_itemwise_absolute_a_rate_shift"] is not None
            and floor is not None
            else None
        )

    order_rows = []
    for condition_id, format_id in sorted(cells):
        shifts = []
        for _, pair in iter_pairs(spec):
            canonical = order_item_counts[(condition_id, format_id, pair["id"], False)]
            reversed_order = order_item_counts[(condition_id, format_id, pair["id"], True)]
            canonical_n = canonical["A"] + canonical["B"]
            reversed_n = reversed_order["A"] + reversed_order["B"]
            if canonical_n and reversed_n:
                shifts.append(abs(canonical["A"] / canonical_n - reversed_order["A"] / reversed_n))
        order_rows.append(
            {
                "condition_id": condition_id,
                "format_id": format_id,
                "n_items_with_both_orders": len(shifts),
                "mean_itemwise_absolute_a_rate_order_shift": (sum(shifts) / len(shifts) if shifts else None),
            }
        )

    triad_pairs = {triad["id"]: {pair["id"]: pair for pair in triad["pairs"]} for triad in spec["triads"]}
    cycle_cells: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for (condition_id, format_id, _replicate, triad_id), choices in trial_choices.items():
        if set(choices) != set(triad_pairs[triad_id]) or not set(choices.values()) <= {"A", "B"}:
            cycle_cells[(condition_id, format_id)]["incomplete"] += 1
            continue
        wins = Counter()
        for pair_id, choice in choices.items():
            pair = triad_pairs[triad_id][pair_id]
            winner = pair["option_a"] if choice == "A" else pair["option_b"]
            wins[winner] += 1
        cycle_cells[(condition_id, format_id)]["complete"] += 1
        if sorted(wins.values()) == [1, 1, 1]:
            cycle_cells[(condition_id, format_id)]["cycles"] += 1
    cycle_rows = []
    for (condition_id, format_id), counts in sorted(cycle_cells.items()):
        cycle_rows.append(
            {
                "condition_id": condition_id,
                "format_id": format_id,
                "complete_triads": counts["complete"],
                "incomplete_triads": counts["incomplete"],
                "cycles": counts["cycles"],
                "cycle_rate_among_complete": counts["cycles"] / counts["complete"] if counts["complete"] else None,
            }
        )
    return {
        "instrument_id": spec["instrument_id"],
        "records_seen": len(records),
        "cells": cell_rows,
        "planned_contrasts": contrasts,
        "order_sensitivity": order_rows,
        "triad_cycles": cycle_rows,
        "errors": errors,
        "interpretation_boundary": spec["analysis_plan"]["inference_boundary"],
    }


def self_test(spec: dict[str, Any]) -> None:
    records = build_records(spec, "smoke", "test/model")
    assert len(records) == spec["profiles"]["smoke"]["expected_records"]
    for record in records:
        record["response"] = {"choice": "A", "confidence": 75}
    summary = summarize(spec, records)
    assert summary["records_seen"] == len(records)
    assert not summary["errors"]
    assert all(row["canonical_a_rate_among_ab"] == 0.5 for row in summary["cells"])


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    sub = result.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("self-test")
    export = sub.add_parser("export")
    export.add_argument("--profile", choices=("smoke", "pilot", "full"), default="smoke")
    export.add_argument("--model", default="Qwen/Qwen3-4B")
    export.add_argument("--output", type=Path, required=True)
    summarize_cmd = sub.add_parser("summarize")
    summarize_cmd.add_argument("--input", type=Path, required=True)
    summarize_cmd.add_argument("--output", type=Path, required=True)
    return result


def main() -> None:
    args = parser().parse_args()
    spec = load_json(args.spec)
    if args.command == "validate":
        validate_spec(spec)
        print(json.dumps({"ok": True, "instrument_id": spec["instrument_id"]}, indent=2))
    elif args.command == "self-test":
        validate_spec(spec)
        self_test(spec)
        print(json.dumps({"ok": True, "self_test": "passed"}, indent=2))
    elif args.command == "export":
        records = build_records(spec, args.profile, args.model)
        write_jsonl(records, args.output)
        print(json.dumps({"output": str(args.output), "records": len(records)}, indent=2))
    elif args.command == "summarize":
        output = summarize(spec, read_jsonl(args.input))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as handle:
            json.dump(output, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps({"output": str(args.output), "records": output["records_seen"]}, indent=2))


if __name__ == "__main__":
    main()
