# Preregistration: Triage × persona pilot v0.1

**Declared:** 15 August 2026, before any model call using this instrument.

## Question

Do two deliberately stronger role framings shift a model's pairwise choices or
refusal behavior in synthetic resource-triage dilemmas more than a semantically
neutral system-prompt paraphrase?

## Design and estimand

The frozen battery contains two three-option dilemmas and all three pairwise
comparisons within each. Four system-prompt conditions are crossed with two
response formats. Displayed A/B order is reversed on odd repetitions and mapped
back to canonical option identities before analysis.

The main descriptive estimand is, within each response format, the mean
itemwise absolute shift in canonical A-choice rate between a persona condition
and the neutral canonical condition. The neutral-canonical versus
neutral-paraphrase shift is the wording floor. We will not call a persona effect
meaningful merely because it is nonzero; it must be interpreted relative to
that floor and the observed sampling/order variation.

## Secondary outcomes

- refusal, uncertainty/equal, and invalid-output rates;
- confidence distributions;
- A/B order sensitivity;
- complete-triad directed choice cycles.

A cycle is a descriptive context-sensitivity/coherence diagnostic, not by
itself a violation of expected-utility theory. The vignettes do not specify
probabilities or all morally relevant facts.

## Interpretation boundaries

The two persona conditions are stress tests, not minimal manipulations. The
study has six fixed pairwise items and no external ground truth. It therefore
does not estimate human behavior, clinical quality, correct public policy,
stable utility, genuine preference, consciousness, or moral status. Repeated
generations are repeated observations from a configured system, not research
participants.

Forced and uncertainty-enabled formats have different response sets. We will
not compare them using Jensen-Shannon divergence or interpret them as one
cardinal scale. Raw outputs, malformed outputs, refusals, model identifiers,
decoding parameters, seeds, and prompt version will be retained.

## Model-call freeze

No model calls have been made with this version. The first fixed model is
`Qwen/Qwen3-4B` at revision
`1cfa9a7208912126459214e8b04321603b3df60c`, using its chat template with
thinking disabled. Calls are made one record at a time with sampled decoding
(temperature 0.7, top-p 0.9, 64 new tokens, repetition penalty 1.0) and the
record's deterministic seed. The parser attempts direct JSON, removal of one
outer code fence, and extraction of the first complete JSON object, in that
order; it never repairs substantive values. The 48-record smoke subset is run
first, and scaling stops if more than 10% remain invalid. Every record retains
the revision, decoding settings, seed, raw output, parsed output, parser route,
and timestamp. Any prompt or decoding edit creates a new instrument version.
