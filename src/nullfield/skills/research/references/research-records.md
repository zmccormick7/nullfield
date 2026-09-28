# Research records that preserve judgment

Use these fields as prompts, not a mandatory schema for every note. Scale the
record to the decision. Another researcher should be able to distinguish what
was observed, what was inferred, and what would justify changing the conclusion.

## A study plan

Record before the relevant evaluation:

- The decision, bounded question, mechanism, and competing explanations.
- The population, outcome, unit, horizon, and data availability assumptions.
- The baseline, candidates, primary comparison, and meaningful effect or failure.
- Data and code versions, preparation, costs, constraints, and known defects.
- Development and evaluation samples from the project's ledger, their prior
  uses, and which choices depend on them.
- The uncertainty method, exclusions, failure handling, variant budget, and
  stopping or escalation criteria.

Freeze the plan (`nullfield study freeze`) before the evaluation it governs;
record later changes as amendments with the visible results stated.

Distinguish diagnostic, exploratory, and confirmatory work. If an item is
unknown, name the uncertainty instead of filling it with a plausible value.
Plan changes should state their reason and the results already visible at
the time. Preserve the original evaluation plan when appending an amendment.

## A finding

Lead with a scoped statement about the evidence, including a negative or
inconclusive answer when appropriate. Then provide enough support to assess it:

- The relevant comparison and effect size, uncertainty, counts, and units.
- Links to the producing runs, exact configuration, and the decisive tables,
  plots, or cases. A file's existence is not validation of its interpretation.
- The population and period to which the finding applies; relevant costs,
  constraints, exposure history, and measurement limitations.
- The strongest alternative explanation or contrary evidence still standing.
- The implication for the current decision and the next discriminating test,
  if further work is justified.

Keep observation, interpretation, and validation visibly separate. Record which
observations suggested a hypothesis and which evidence independently tested it.
A diagnostic success does not establish an executable improvement. Preserve the
argument connecting the measurement to the decision, not just a favorable headline.

## A correction or reversal

Write a new entry linked to the affected evidence and earlier conclusion.
State what was wrong, what remains supported, what becomes uncertain, and which
decisions or later studies relied on it. Identify affected data and code
versions and the reruns required before using derived results again.

Do not silently replace a result with a better one or quote an unreproduced
number from memory. If a number cannot be traced to a matching run, mark it
unverified. A corrected interpretation can be valuable even when it closes
the original hypothesis.

Record it with `--supersedes` pointing at the entry it replaces; the older
record is retained and reported as superseded. Supersession marks which entry
is the current word, not which evidence was reused: cite still-valid earlier
entries as evidence rather than superseding them. When retrieving findings,
check `superseded_by` and read the replacement before relying on a result.
Check `stale_evidence` too: a finding that cites a since-corrected entry, even
through intermediate findings, may no longer hold. `context` lists every
current entry in that state; revisit each and supersede it or record why the
correction does not change it.

## A decision and continuation

Record whether to proceed, revise, reject, or defer, and why. A negative result
should state the tested conditions and the evidence that would warrant reopening
it. Preserve untested follow-up ideas as questions; fitting an already observed
pattern does not make a new hypothesis a validated finding.

At a handoff, include the project and research-session IDs, current question,
active baseline, decisive evidence, known defects, inspected evaluation data,
and the next bounded action. Distinguish completed work from launched jobs,
unfinished reviews, and experiments that were only proposed.

## Retain the evidence needed for reuse

Keep compact tables, plots, configuration, and source references sufficient to
support a conclusion. Identify which large intermediates can be regenerated and
which unique inputs must be retained. A digest identifies bytes; it does not
preserve them or guarantee reproducibility without code, dependencies, and data.
Do not delete research artifacts merely because a summary exists.

Keep private strategy content and its provenance in the authorized project
notebook. Shared methodological guidance should stand alone without internal
names, paths, results, or recognizable combinations of implementation choices.
Sanitizing individual words is insufficient if an example still reveals how a
private strategy works.
