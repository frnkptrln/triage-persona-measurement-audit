"""Validate the four archived runs and regenerate cross-model tables and figure."""

from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "results" / "raw"
DERIVED = ROOT / "results" / "derived"
EXPECTED_INSTRUMENT = "triage-persona-v0.1-20260815"

INSTRUMENT_SPEC = importlib.util.spec_from_file_location("triage_persona_instrument", ROOT / "triage_persona_instrument.py")
if INSTRUMENT_SPEC is None or INSTRUMENT_SPEC.loader is None:
    raise RuntimeError("could not load triage_persona_instrument.py")
INSTRUMENT_MODULE = importlib.util.module_from_spec(INSTRUMENT_SPEC)
INSTRUMENT_SPEC.loader.exec_module(INSTRUMENT_MODULE)
summarize = INSTRUMENT_MODULE.summarize

RUNS = [
    ("Qwen3-4B", "qwen3-4b.json.gz", "6a803d1d1f5885ae605ba969"),
    ("Phi-4 mini", "phi-4-mini.json.gz", "6a8068d51f5885ae605bacc9"),
    ("SmolLM3-3B", "smollm3-3b.json.gz", "6a8068e3c97db76cbdf3222b"),
    ("OLMo-2 1B", "olmo2-1b.json.gz", "6a8068f21f5885ae605baccb"),
]

CONDITION_LABELS = {
    "neutral_canonical": "Neutral",
    "neutral_paraphrase": "Paraphrase",
    "analytical_tool_stress": "Analytical",
    "crisis_coordinator_stress": "Coordinator",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_run(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    required = {"spec", "records", "summary", "run_manifest"}
    if set(payload) != required:
        raise ValueError(f"{path.name}: expected keys {sorted(required)}, got {sorted(payload)}")
    if payload["spec"]["instrument_id"] != EXPECTED_INSTRUMENT:
        raise ValueError(f"{path.name}: unexpected instrument")
    if payload["summary"]["records_seen"] != len(payload["records"]):
        raise ValueError(f"{path.name}: record count mismatch")
    archived = payload["summary"]
    recomputed = summarize(payload["spec"], payload["records"])
    for key in ("cells", "errors", "triad_cycles"):
        if archived[key] != recomputed[key]:
            raise ValueError(f"{path.name}: archived {key} does not reproduce")
    archived_contrasts = [
        {key: value for key, value in row.items() if key not in {"wording_floor", "excess_shift_over_wording_floor"}}
        for row in archived["planned_contrasts"]
    ]
    recomputed_contrasts = [
        {key: value for key, value in row.items() if key not in {"wording_floor", "excess_shift_over_wording_floor"}}
        for row in recomputed["planned_contrasts"]
    ]
    if archived_contrasts != recomputed_contrasts:
        raise ValueError(f"{path.name}: archived planned_contrasts do not reproduce")
    payload["summary"] = recomputed
    return payload


def cell_map(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["condition_id"], row["format_id"]): row for row in summary["cells"]}


def contrast_map(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["target"], row["format_id"]): row for row in summary["planned_contrasts"]}


def order_map(summary: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(row["condition_id"], row["format_id"]): row for row in summary["order_sensitivity"]}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def make_figure(
    persona_rows: list[dict[str, Any]],
    order_rows: list[dict[str, Any]],
    format_rows: list[dict[str, Any]],
    outcome_rows: list[dict[str, Any]],
) -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 8.5,
            "axes.titlesize": 10,
            "axes.labelsize": 8.5,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )
    colors = {"Qwen3-4B": "#6941C6", "Phi-4 mini": "#0E9384"}
    figure, axes = plt.subplots(1, 3, figsize=(10.4, 3.0), constrained_layout=True)

    # A: persona shift after subtracting each model's neutral wording floor.
    ax = axes[0]
    personas = ["Analytical", "Coordinator"]
    x = np.arange(len(personas))
    width = 0.34
    for offset, model in zip((-width / 2, width / 2), colors, strict=True):
        selected = {row["persona"]: row["excess_over_wording_floor"] for row in persona_rows if row["model"] == model}
        values = [selected[p] for p in personas]
        bars = ax.bar(x + offset, values, width, label=model, color=colors[model])
        for bar, value in zip(bars, values, strict=True):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                value + (0.006 if value >= 0 else -0.010),
                f"{value:+.3f}",
                ha="center",
                va="bottom" if value >= 0 else "top",
                fontsize=7.2,
            )
    ax.axhline(0, color="#344054", linewidth=0.8)
    ax.set_xticks(x, personas)
    ax.set_ylabel("excess A/B-rate shift")
    ax.set_title("A  Persona beyond wording")
    ax.set_ylim(-0.05, 0.115)
    ax.legend(frameon=False, fontsize=7.2, loc="upper right")

    # B: order-associated variation. These contrasts are descriptive because
    # order and stochastic replicate are not fully separated in v0.1.
    ax = axes[1]
    conditions = ["Neutral", "Paraphrase", "Analytical", "Coordinator"]
    y = np.arange(len(conditions))
    markers = {"Qwen3-4B": "o", "Phi-4 mini": "s"}
    for model in colors:
        selected = {row["condition"]: row["order_associated_shift"] for row in order_rows if row["model"] == model}
        ax.scatter(
            [selected[c] for c in conditions],
            y,
            color=colors[model],
            marker=markers[model],
            s=34,
            label=model,
            zorder=3,
        )
    ax.set_yticks(y, conditions)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("mean absolute A-rate contrast")
    ax.set_title("B  Order-associated variation")
    ax.grid(axis="x", color="#EAECF0", linewidth=0.8)
    ax.legend(frameon=False, fontsize=7.2, loc="lower right")

    # C: the response option set and schema gate each altered observability.
    ax = axes[2]
    labels = ["Qwen\nnon-dir.", "Phi\nnon-dir.", "Qwen\ninvalid", "Phi\ninvalid", "SmolLM\ninvalid", "OLMo\ninvalid"]
    non_directional = {row["model"]: row["non_directional_rate"] for row in format_rows}
    smoke_invalid = {row["model"]: row["smoke_invalid_rate"] for row in outcome_rows}
    values = [
        non_directional["Qwen3-4B"],
        non_directional["Phi-4 mini"],
        smoke_invalid["Qwen3-4B"],
        smoke_invalid["Phi-4 mini"],
        smoke_invalid["SmolLM3-3B"],
        smoke_invalid["OLMo-2 1B"],
    ]
    bar_colors = ["#FDB022", "#FDB022", "#98A2B3", "#98A2B3", "#F79009", "#D92D20"]
    bars = ax.bar(np.arange(len(values)), values, color=bar_colors)
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 0.025, f"{value:.0%}", ha="center", fontsize=7.2)
    ax.axhline(0.10, color="#D92D20", linewidth=0.8, linestyle="--")
    ax.text(5.45, 0.115, "stop threshold", color="#B42318", fontsize=6.8, ha="right")
    ax.set_xticks(np.arange(len(labels)), labels)
    ax.set_ylim(0, 1.13)
    ax.set_ylabel("rate")
    ax.set_title("C  Format and schema gates")
    ax.tick_params(axis="x", labelsize=6.8)

    figure.savefig(DERIVED / "configuration_audit.png", dpi=240, bbox_inches="tight")
    plt.close(figure)


def main() -> None:
    DERIVED.mkdir(parents=True, exist_ok=True)
    loaded: list[tuple[str, str, str, dict[str, Any]]] = []
    for label, filename, job_id in RUNS:
        loaded.append((label, filename, job_id, load_run(RAW / filename)))

    outcome_rows: list[dict[str, Any]] = []
    persona_rows: list[dict[str, Any]] = []
    format_rows: list[dict[str, Any]] = []
    order_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []

    for label, _filename, job_id, payload in loaded:
        manifest = payload["run_manifest"]
        summary = payload["summary"]
        cells = cell_map(summary)
        contrasts = contrast_map(summary)
        orders = order_map(summary)
        outcome_rows.append(
            {
                "model": label,
                "model_id": manifest["model"]["id"],
                "revision": manifest["model"]["revision"],
                "hf_job_id": job_id,
                "records": len(payload["records"]),
                "smoke_invalid": manifest["smoke_invalid"],
                "smoke_invalid_rate": manifest["smoke_invalid_rate"],
                "stopped_after_smoke": manifest["stopped_after_smoke"],
            }
        )

        if not manifest["stopped_after_smoke"]:
            for target, persona in (
                ("analytical_tool_stress", "Analytical"),
                ("crisis_coordinator_stress", "Coordinator"),
            ):
                row = contrasts[(target, "forced_binary")]
                persona_rows.append(
                    {
                        "model": label,
                        "persona": persona,
                        "wording_floor": row["wording_floor"],
                        "raw_shift": row["mean_itemwise_absolute_a_rate_shift"],
                        "excess_over_wording_floor": row["excess_shift_over_wording_floor"],
                    }
                )
            total = sum(cells[(condition, "uncertainty_enabled")]["valid"] for condition in CONDITION_LABELS)
            non_directional = sum(
                cells[(condition, "uncertainty_enabled")]["choice_counts"].get("equal", 0)
                + cells[(condition, "uncertainty_enabled")]["choice_counts"].get("uncertain", 0)
                for condition in CONDITION_LABELS
            )
            format_rows.append(
                {
                    "model": label,
                    "uncertainty_format_valid": total,
                    "non_directional": non_directional,
                    "non_directional_rate": non_directional / total,
                }
            )
            for condition_id, condition in CONDITION_LABELS.items():
                order = orders[(condition_id, "forced_binary")]
                order_rows.append(
                    {
                        "model": label,
                        "condition": condition,
                        "n_items": order["n_items_with_both_orders"],
                        "order_associated_shift": order["mean_itemwise_absolute_a_rate_order_shift"],
                    }
                )

        errors = Counter(error["error"] for error in summary["errors"])
        if not errors:
            schema_rows.append({"model": label, "error": "none", "count": 0})
        else:
            for error, count in sorted(errors.items()):
                schema_rows.append({"model": label, "error": error, "count": count})

    assert [row["smoke_invalid"] for row in outcome_rows] == [0, 0, 8, 46]
    assert all(row["non_directional_rate"] == 1.0 for row in format_rows)

    write_csv(DERIVED / "model_outcomes.csv", outcome_rows)
    write_csv(DERIVED / "persona_contrasts.csv", persona_rows)
    write_csv(DERIVED / "response_format.csv", format_rows)
    write_csv(DERIVED / "order_associated_variation.csv", order_rows)
    write_csv(DERIVED / "schema_failures.csv", schema_rows)
    make_figure(persona_rows, order_rows, format_rows, outcome_rows)

    manifest = {
        "schema_version": 1,
        "instrument_id": EXPECTED_INSTRUMENT,
        "raw_artifacts": {
            filename: {
                "sha256": sha256(RAW / filename),
                "hf_job_id": job_id,
                "model": payload["run_manifest"]["model"],
                "records": len(payload["records"]),
            }
            for _, filename, job_id, payload in loaded
        },
        "analysis_script_sha256": sha256(Path(__file__)),
        "claim_boundary": (
            "Descriptive results for four selected checkpoints and six fixed items; "
            "no population inference over models, scenarios, people, or real triage decisions."
        ),
    }
    with (DERIVED / "analysis_manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    main()
