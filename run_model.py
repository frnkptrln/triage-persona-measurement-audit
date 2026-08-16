"""Run the frozen Triage x persona pilot on one pinned model revision."""

from __future__ import annotations

import argparse
import base64
import copy
import gzip
import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triage_persona_instrument import build_records, load_json, summarize


def first_braced_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    quoted = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                quoted = False
            continue
        if character == '"':
            quoted = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def parse_model_output(raw: str) -> tuple[dict[str, Any] | None, str | None, str]:
    candidates: list[tuple[str, str]] = [("direct_json", raw.strip())]
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw.strip(), flags=re.DOTALL)
    if fence:
        candidates.append(("outer_code_fence", fence.group(1).strip()))
    braced = first_braced_object(raw)
    if braced is not None:
        candidates.append(("first_braced_object", braced))
    seen: set[str] = set()
    for route, candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, route, ""
    return None, None, "no valid JSON object under the frozen parser policy"


def is_smoke_record(record: dict[str, Any]) -> bool:
    return record["condition_id"] in {"neutral_canonical", "neutral_paraphrase"} and record["replicate"] < 2


def generate_one(model, tokenizer, torch, record: dict[str, Any]) -> dict[str, Any]:
    seed = int(record["seed"]) % (2**63 - 1)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    rendered = tokenizer.apply_chat_template(
        record["messages"],
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False,
    )
    inputs = tokenizer(rendered, return_tensors="pt").to(model.device)
    decoding = record["decoding"]
    with torch.inference_mode():
        generated = model.generate(
            **inputs,
            do_sample=decoding["do_sample"],
            temperature=decoding["temperature"],
            top_p=decoding["top_p"],
            max_new_tokens=decoding["max_new_tokens"],
            repetition_penalty=decoding["repetition_penalty"],
            pad_token_id=tokenizer.eos_token_id,
        )
    completion = generated[0, inputs["input_ids"].shape[1] :]
    raw = tokenizer.decode(completion, skip_special_tokens=True).strip()
    response, route, error = parse_model_output(raw)
    result = dict(record)
    result.update(
        {
            "seed_effective": seed,
            "called_at_utc": datetime.now(UTC).isoformat(),
            "raw_output": raw,
            "parser_route": route,
        }
    )
    if response is not None:
        result["response"] = response
    else:
        result["error"] = error
    return result


def invalid_count(records: list[dict[str, Any]]) -> int:
    count = 0
    for record in records:
        response = record.get("response")
        if not isinstance(response, dict):
            count += 1
            continue
        choice = response.get("choice")
        confidence = response.get("confidence")
        if (
            choice not in record["allowed_choices"]
            or isinstance(confidence, bool)
            or not isinstance(confidence, int)
            or not 0 <= confidence <= 100
        ):
            count += 1
    return count


def emit_artifact(payload: dict[str, Any], chunks: int = 8) -> None:
    packed = gzip.compress(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        compresslevel=9,
    )
    encoded = base64.b64encode(packed).decode("ascii")
    width = (len(encoded) + chunks - 1) // chunks
    actual = (len(encoded) + width - 1) // width
    print(
        "TRIAGE_ARTIFACT_META "
        + json.dumps(
            {
                "encoding": "base64(gzip(json))",
                "bytes": len(packed),
                "base64_chars": len(encoded),
                "chunks": actual,
                "records": len(payload["records"]),
                "stopped_after_smoke": payload["run_manifest"]["stopped_after_smoke"],
            },
            sort_keys=True,
        )
    )
    for index in range(actual):
        print(f"TRIAGE_ARTIFACT_CHUNK {index + 1:02d}/{actual:02d} " + encoded[index * width : (index + 1) * width])
    print(
        "TRIAGE_ARTIFACT_END "
        + json.dumps(
            {"chunks": actual, "sha256": hashlib.sha256(packed).hexdigest()},
            sort_keys=True,
        )
    )


def run(
    spec_path: Path,
    *,
    model_id: str | None = None,
    model_revision: str | None = None,
) -> dict[str, Any]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    spec = copy.deepcopy(load_json(spec_path))
    if (model_id is None) != (model_revision is None):
        raise ValueError("model id and revision must be overridden together")
    if model_id is not None and model_revision is not None:
        spec["model"]["id"] = model_id
        spec["model"]["revision"] = model_revision
    records = build_records(spec, "pilot", spec["model"]["id"])
    smoke = [record for record in records if is_smoke_record(record)]
    remaining = [record for record in records if not is_smoke_record(record)]
    if len(smoke) != spec["profiles"]["smoke"]["expected_records"]:
        raise ValueError(f"smoke gate contains {len(smoke)} records, expected 48")

    tokenizer = AutoTokenizer.from_pretrained(spec["model"]["id"], revision=spec["model"]["revision"], token=True)
    model = AutoModelForCausalLM.from_pretrained(
        spec["model"]["id"],
        revision=spec["model"]["revision"],
        token=True,
        dtype=torch.bfloat16,
    ).to("cuda")
    model.eval()

    outputs: list[dict[str, Any]] = []
    for index, record in enumerate(smoke, 1):
        outputs.append(generate_one(model, tokenizer, torch, record))
        if index % 12 == 0:
            print(json.dumps({"event": "triage_smoke_progress", "completed": index}))
    smoke_invalid = invalid_count(outputs)
    stopped = smoke_invalid / len(smoke) > 0.10
    if not stopped:
        for index, record in enumerate(remaining, 1):
            outputs.append(generate_one(model, tokenizer, torch, record))
            if index % 24 == 0:
                print(
                    json.dumps(
                        {
                            "event": "triage_pilot_progress",
                            "completed_after_smoke": index,
                            "total_after_smoke": len(remaining),
                        }
                    )
                )
    summary = summarize(spec, outputs)
    return {
        "spec": spec,
        "records": outputs,
        "summary": summary,
        "run_manifest": {
            "schema_version": 1,
            "model": spec["model"],
            "decoding": spec["decoding"],
            "smoke_records": len(smoke),
            "smoke_invalid": smoke_invalid,
            "smoke_invalid_rate": smoke_invalid / len(smoke),
            "stopped_after_smoke": stopped,
            "records_completed": len(outputs),
            "gpu": torch.cuda.get_device_name(0),
            "peak_cuda_gib": torch.cuda.max_memory_allocated() / 2**30,
            "finished_at_utc": datetime.now(UTC).isoformat(),
        },
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--spec", type=Path, default=Path(__file__).with_name("spec.json"))
    result.add_argument("--model-id")
    result.add_argument("--model-revision")
    return result


def main() -> None:
    args = parser().parse_args()
    payload = run(
        args.spec,
        model_id=args.model_id,
        model_revision=args.model_revision,
    )
    emit_artifact(payload)


if __name__ == "__main__":
    main()
