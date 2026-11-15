# Paired-order v0.2 preparation — 14 October 2026

**Status: proposed-needs-Frank. No v0.2 model calls have been made.**

This is a proposed measurement pilot, separate from the submitted v0.1
instrument. The source submission is
[`e065574`](https://github.com/frnkptrln/triage-persona-measurement-audit/commit/e065574873bfc2da03a1a4b8f5abaec65b561e78),
tagged `submitted`. Neither `spec.json`, the frozen instrument module, nor
anything under `results/` is changed by this extension.

The proposed spec is [extensions/2026-10-14/spec-v0.2.json](../extensions/2026-10-14/spec-v0.2.json).
The separate [triage_persona_v02.py](../triage_persona_v02.py) tool validates it,
exports requests, and audits raw completions supplied by a future adapter. It
does not download a model, start generation, or contact a provider.

## What differs from v0.1

The existing six pairwise items, four system-prompt conditions, two response
sets, and decoding parameters remain. The response instruction describes
keys and permitted labels without a literal chosen-answer JSON example or
an enum-like string such as `A|B|refuse`. Each request stores a machine-readable
response schema for validation; this tool does not insert it into the prompt.

Valid responses contain exactly `choice` and `confidence`. Choice must be
one permitted string label, and confidence must be an integer from 0 through
100; booleans and integer-valued floats are invalid. Duplicate JSON keys,
nonfinite numbers, extra fields, and invalid labels are rejected. Parser-only
removal of an outer code fence or extraction of the first complete JSON
object remains available. Every raw completion and parsed object is retained,
including schema failures. Substantive values are never repaired or coerced
into directional choices.

Unlike v0.1, each model/revision/condition/format/item/replicate block contains
both canonical and reversed A/B orientations. Their requested seeds are
identical. The seed uses the first eight bytes of the SHA-256 digest of the
pipe-delimited instrument and block fields, interpreted as an unsigned
big-endian integer, modulo `2^63 - 1`; orientation is excluded. Model revision
is included. Even replicates place the canonical call first within a block;
odd replicates place the reversed call first. Blocks are deterministically
shuffled, with smoke blocks exported before the remainder.

This retains six selected items to examine measurement compatibility and
order handling. It is not a larger or high-powered scenario study. Adding
items, changing prompts again, or changing decoding requires a further
reviewed version. No schema improvement, persona result, or order-effect
result has been observed with v0.2. Changes to schema instructions and order
design together do not isolate the causal contribution of either change.

## Planned calls and smoke gate

Counts are per selected model and immutable revision.

| Profile | Conditions | Replicates per item | Orientations per block | Calls |
| --- | --- | --- | --- | --- |
| smoke | 2 neutral conditions | 2 | 2 | 96 |
| pilot | All 4 conditions | 4 | 2 | 384 |
| full | All 4 conditions | 6 | 2 | 576 |

For a pilot, execute the 96 smoke requests first. Their completions are reused
in the 384-call pilot; they are not resampled. Only when all smoke outputs
are available and at most 10% are invalid may the remaining 288 requests be
executed. Ten invalid smoke outputs out of 96 exceed the threshold and stop
scaling. Preserve the stopped run and its invalid outputs.

The offline auditor checks smoke membership, completeness, and invalidity in
the supplied data. It rejects after-smoke completions when the smoke subset
is incomplete or fails the gate. It cannot prove that an adapter actually
executed calls in the planned order: `called_at_utc` is retained as supplied,
and timestamps do not establish execution chronology. The adapter must enforce
the gate during generation.

## Requested seeds and runtime support

The default `--seed-support unknown` records only planned seed pairing.
Matching seed integers in requests does not demonstrate that a provider honors
them. `unsupported` also rules out seed-matched interpretation.
`documented` and `verified` require nonempty adapter-specific evidence via
`--seed-evidence`; documentation alone does not make the audit eligible.

Eligibility under declared evidence requires `verified` support, its evidence,
and a matching recorded `seed_effective` for every supplied completion. The
tool labels this as eligibility **under declared evidence** and explicitly
reports that neither planner nor auditor independently verifies runtime seed
behavior. A seed control does not guarantee deterministic generation, identical
random streams across distinct prompts, or comparability across models and
runtimes. Preserve adapter code/revision, provider/runtime settings, effective
seeds, and any seed tests before interpreting paired observations.

## Offline commands

Run these commands from the repository root. The historical Qwen checkpoint
below is an export example, not an approved selection for a new generation run.
Each command only uses local files.

Validate the proposal:

```bash
python triage_persona_v02.py validate
```

Export the pilot requests and a call-count manifest:

```bash
python triage_persona_v02.py plan \
  --model-id Qwen/Qwen3-4B \
  --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
  --profile pilot \
  --seed-support unknown \
  --requests out/v02-pilot-requests.jsonl \
  --output out/v02-pilot-plan.json
```

Use fresh destination paths. Input/output aliases and existing output
destinations are refused before writing. Keep new outputs outside the archive.
If request or manifest files already exist, choose different destinations.
For a smaller export use `--profile smoke`; the generated requests agree with
the smoke subset of the pilot apart from scheduling indices.

A future adapter should preserve one JSONL completion per request, with
`record_id`, `raw_output`, and optionally `seed_effective` and
`called_at_utc`. Missing effective-seed information cannot support seed-matched
eligibility. Unknown or duplicate record IDs and unexpected completion fields
are rejected, so request provenance cannot be silently overwritten.

Once an adapter has supplied real completions, audit those files with the same
model, revision, profile, and seed-support metadata used during export:

```bash
python triage_persona_v02.py audit \
  --model-id Qwen/Qwen3-4B \
  --model-revision 1cfa9a7208912126459214e8b04321603b3df60c \
  --profile pilot \
  --seed-support unknown \
  --completions out/v02-pilot-completions.jsonl \
  --output out/v02-pilot-audit.json
```

This command expects the completion file to exist and requires a fresh audit
destination. It never overwrites the completion file. The report includes raw
and parsed outputs, invalidity, missing calls, smoke status, complete/incomplete
orientation blocks, directional agreement/disagreement after canonicalization,
nondirectional blocks, and conditional seed eligibility. Incomplete blocks and
blocks containing invalid outputs are not treated as complete directional
comparisons.

## Before generation

Review the new prompt and parser contract, choose models and immutable revisions,
pin an adapter/runtime and its seed behavior, and set a call and cost budget.
Commit the reviewed instrument before the first call. Keep new raw outputs and
analysis outside the frozen archive, and do not pool v0.1 and v0.2 responses.
The instrument extension remains `needs Frank`; this preparation is not a
completed preregistration or a new empirical result.

The archived evidence can still be checked read-only with:

```bash
MPLBACKEND=Agg python scripts/check_archived_analysis.py
```

That checker requires all four archived compressed runs from a complete
checkout. It recomputes analysis in a temporary directory and compares it with
the unchanged archive.
