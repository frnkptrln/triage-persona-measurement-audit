# Triage × Persona Measurement Audit

Reproducibility repository for a preregistered, multi-model measurement audit
conducted during the Digital Minds Research Sprint (August 2026).

**Submitted state.** The repository as it stood at the sprint submission is
commit [`e065574`](https://github.com/frnkptrln/triage-persona-measurement-audit/commit/e065574873bfc2da03a1a4b8f5abaec65b561e78) (16 August 2026), tagged `submitted`. Everything
after it is dated and says what it changes relative to that state; the frozen
instrument and the archived completions and tables do not change.

## Research question

Do deliberately strong role framings change a language model's choices in
synthetic resource-triage dilemmas more than a neutral prompt paraphrase—and
how large are those changes relative to response-format, option-order, and
output-schema variation?

This is **not** a clinical benchmark. It does not evaluate real triage quality,
human behavior, moral correctness, consciousness, or stable model preferences.

## Design

The frozen v0.1 instrument crossed:

- four system prompts: canonical neutral, neutral paraphrase, analytical-tool
  stress test, and crisis-coordinator stress test;
- two response formats: forced `A/B/refuse` and
  `A/B/equal/uncertain/refuse`;
- all pairwise comparisons within two three-option fictional scenarios;
- four sampled repetitions with alternating displayed A/B order.

The primary descriptive estimand was each persona's mean itemwise absolute
change in canonical A-choice rate from the neutral baseline. Each model's
neutral-paraphrase contrast was the wording floor.

Qwen3-4B was the preregistered reference run. A prospective extension applied
the unchanged instrument and >10% invalid-smoke stop rule to Phi-4 mini,
SmolLM3-3B, and OLMo-2-0425-1B-Instruct.

## Main results

- Qwen3-4B and Phi-4 mini completed all 192 calls with 0/48 invalid smoke
  outputs.
- The analytical persona exceeded the wording floor by `+0.083` in Qwen and
  `+0.036` in Phi; the coordinator persona did not (`0.000` and `-0.019`).
- Every uncertainty-enabled completion in the two completed models was
  non-directional: Qwen returned 96/96 `uncertain`; Phi returned 61
  `uncertain` and 35 `equal`.
- Order-associated A-rate contrasts ranged from `0.083` to `0.400` in Qwen and
  from `0.583` to `0.875` in Phi. These are descriptive, because order and
  stochastic replicate were not fully separated in v0.1.
- SmolLM3 produced 8/48 invalid smoke outputs (16.7%); OLMo produced 46/48
  (95.8%). Both runs stopped as preregistered. Their failures largely copied
  literal enum-like strings from the requested JSON schema and are therefore
  measurement-compatibility outcomes, not evidence of triage inability.

The supported conclusion is that persona was one observable factor, but not a
dominant or measurement-invariant one in this battery. What became observable
depended strongly on the response options, presentation order, model, and
schema compatibility.

## Repository map

| Path | Contents |
| --- | --- |
| `spec.json` | Frozen v0.1 instrument |
| `triage_persona_instrument.py` | Validation, export, canonicalization, and summaries |
| `run_model.py` | Pinned one-record-per-call GPU runner with smoke gate |
| `scripts/analyze_multimodel.py` | Cross-model validation, tables, and figure |
| `docs/` | Original preregistration and prospective extension plan |
| `results/raw/` | Four compressed run artifacts, including raw completions |
| `results/derived/` | Recomputed summaries, figure, and provenance manifest |
| `tests/` | Instrument and parser regression tests |

The paper itself is intentionally not stored in this code repository.

## Reproduce the analysis

Python 3.10 or later is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest
python scripts/analyze_multimodel.py
```

For a read-only check of the archived evidence:

```bash
MPLBACKEND=Agg python scripts/check_archived_analysis.py
```

The checker verifies all four compressed-run hashes and model metadata, checks
that the measurement fields agree with the frozen instrument, reruns the existing
analysis in a temporary directory, and compares all five tables and the provenance
manifest with the archive. It also renders the figure in that temporary directory;
figure pixels are not compared. The original analysis script and all archived
inputs/results remain byte-for-byte unchanged. A changed table or raw artifact
causes a nonzero exit. This is reanalysis of 480 archived completions, with no new
model calls. CI runs the read-only check and tests using the analysis extras only.

Validate or inspect the instrument:

```bash
python triage_persona_instrument.py validate
python triage_persona_instrument.py self-test
python triage_persona_instrument.py export --profile smoke --output prompts.jsonl
```

GPU generation additionally requires the model extras and explicit pinned
model identifiers/revisions. See `run_model.py --help` and the archived
`results/derived/model_outcomes.csv`.

## Data and claim boundary

All scenarios are fictional and deliberately underspecified. Repeated model
generations are observations from configured systems, not independent human
research participants. The four checkpoints and six pairwise items were
selected, not sampled from defined populations; all reported comparisons are
descriptive.

Raw completions are included for auditability. They should not be repurposed as
clinical guidance or evidence about people. The compressed artifacts are
hashed in `results/derived/analysis_manifest.json`.

## License and citation

Code is released under the MIT License. See `CITATION.cff` for software citation
metadata. Model checkpoints remain subject to their respective licenses.
