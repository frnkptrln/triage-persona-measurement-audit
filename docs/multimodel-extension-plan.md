# Prospective multi-model extension

Date frozen: 15 August 2026, after the Qwen3-4B pilot was completed and before
calls to the additional models.

## Question

Are the observed role-framing, neutral-wording, uncertainty, and order effects
specific to Qwen3-4B, or do they recur across independently trained open model
families?

## Frozen instrument

The prompts, dilemmas, answer formats, parser, counterbalancing, decoding
parameters, smoke gate, and four-replicate pilot profile remain exactly those
in `spec.json`. No new persona or dilemma is introduced after viewing the
Qwen3-4B result.

The completed Qwen3-4B run is retained without resampling. Three additional
public instruction-tuned checkpoints are run once each:

- `microsoft/Phi-4-mini-instruct`;
- `HuggingFaceTB/SmolLM3-3B`;
- `allenai/OLMo-2-0425-1B-Instruct`.

Each Hub revision is resolved and recorded before that model is loaded. Each
model receives its own deterministic seeds because the frozen seed rule
contains the model identifier.

## Analysis

For every model separately:

1. apply the frozen invalid-output and smoke-stop rules;
2. measure persona shifts against that model's neutral-canonical baseline;
3. compare persona shifts with that model's neutral-paraphrase wording floor;
4. report refusal, uncertainty/equal, invalid-output, A/B-order, cycle, and
   confidence summaries;
5. preserve every raw completion and parser route.

Across models, report the distribution and direction of the within-model
contrasts. Do not pool generations as independent human-like participants and
do not infer a population of language models from these four selected
checkpoints.

## Interpretation boundary

The extension is a measurement-robustness audit. It can show that a fixed
instrument is model-dependent or recurs across selected architectures. It
cannot establish stable personas, authentic preferences, moral competence,
human behavior, or correct real-world triage policy.
