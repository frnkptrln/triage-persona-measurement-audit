# Paired-order v0.2 preparation — 14 October 2026

**Status: proposed instrument extension; needs Frank. No v0.2 model calls have been made.**

This extension addresses two v0.1 measurement limitations: literal enum-like
JSON examples were copied by some models, and option order was confounded with
the stochastic replicate. The submitted state `e065574`, frozen instrument,
archived completions, and derived results remain unchanged.

Expected changes are a dated extension spec, a separate offline planner and
completion auditor, tests, a package-module entry, and a README entry. The new
spec keeps the existing six items, four conditions, and decoding settings.
Every model/condition/format/item/replicate block contains both orientations
with the same requested seed. Provider seed support is recorded explicitly;
unknown or unsupported seed handling cannot support seed-matched claims.

The plan exports requests and audits externally supplied raw completions.
It does not call or download any model. Before a generation run, review the
new instrument, pin model revisions and adapter/runtime versions, decide a
budget, and commit the reviewed spec. Invalid outputs are retained without
value repair. Details and executable examples will be added with the planner.
