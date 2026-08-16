# Analysis notes and deviations

## Confirmatory stage

The Qwen3-4B run followed the preregistered v0.1 instrument and smoke gate. No
prompt, choice, parser, or outcome was repaired after generation.

## Prospective extension

The three-model extension plan was dated after the Qwen reference result and
before calls to Phi-4 mini, SmolLM3, and OLMo. The prompts, response formats,
parser, decoding configuration, seed rule, and >10% invalid smoke-stop rule
were unchanged. SmolLM3 and OLMo are reported as stopped protocol outcomes.

## Terminology correction

The preregistration calls the displayed-order summary “order sensitivity.” In
v0.1, canonical and reversed orders occur on different stochastic repetitions,
so presentation order and sampling variation are not fully separated. The
paper therefore uses **order-associated variation** and does not assign the
contrast a causal interpretation.

## Schema failures

The frozen parser did not coerce literal strings such as `A|B|refuse` into a
valid choice. These outputs are retained as invalid. Because the literal union
appeared in the prompt's JSON example, the high invalid rates in two models
are interpreted as prompt–schema compatibility failures, not as refusal or
inability to reason about the scenarios.

## Inference boundary

The six items and four checkpoints are fixed selections. Repeated generations
are not independent human-like participants. No population inference is made
over models, scenarios, people, or real triage decisions.
