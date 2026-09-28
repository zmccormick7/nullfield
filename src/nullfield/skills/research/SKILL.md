---
name: research
description: >-
  Work on quant research projects with the nullfield CLI: select or resume a project,
  consult its notebook, design discriminating experiments, audit measurements,
  and preserve evidence and corrections. Use when the user invokes research with
  a project alias or asks to continue a registered quantitative research study.
---

# Research

Use the installed `nullfield` CLI for project identity and research records. The host
(Codex or Claude Code) supplies reasoning, editing, execution tools, and session
management. Projects can span repositories or share a repository. The current
working directory never identifies the active research project.

## Select and orient

- If the user supplied a research-session UUID, run `nullfield session show UUID`,
  then `nullfield context --session UUID`.
- If the user supplied a project alias, run `nullfield session start ALIAS --agent codex`
  (use `--agent claude` in Claude Code). Save the returned research-session UUID
  in the conversation and any continuation summary; use `--session UUID` for
  subsequent work. A new agent conversation normally gets a new research session.
- With no selection, run `nullfield project list` and ask which project to use. If a
  session association was lost, don't infer it from the latest session or cwd.
- To create a project, use `nullfield project create ALIAS --name 'NAME' --objective
  'OBJECTIVE' --path /absolute/notebook/path`. The notebook directory must be new
  or empty. Register an existing notebook with `nullfield project register ALIAS PATH`.
- Read `nullfield context --session UUID`. Show the project name and current direction
  briefly, then search related work before proposing an investigation. Context
  is an index; open relevant plans, findings, decisions, and negative results.

If `NULLFIELD_HOME` is configured, the CLI uses it. Otherwise its registry lives under
`~/.nullfield`. A user-supplied registry can be used consistently through
`nullfield --home PATH ...`. Resource access still follows the host's workspace rules;
registration alone does not grant filesystem access.

## Research judgment

Optimize for a defensible answer to the research question. A higher backtest
score is useful only if the measurement represents the intended economic decision.
Prefer the cheapest experiment that can resolve a consequential uncertainty.

- **Be especially cautious about overfitting and overtrading.** Treat these as
  primary failure modes. Require strong evidence that added complexity or
  trading activity improves the decision. Count research choices as well as
  fitted parameters, and evaluate incremental trading benefits after realistic
  costs and uncertainty. Compare with simpler and lower-turnover alternatives;
  retaining the current position or taking no position can be valid decisions,
  subject to the project's risk limits.
- **Develop understanding and evidence together.** Write a plausible mechanism
  and a prediction that could fail, then inspect actual observations early.
  Treat rough calculations as guides to the next measurement. A story alone
  does not validate a result; a historical association alone does not explain it.
  Require a coherent economic explanation and empirical support before
  recommending implementation; keep unexplained predictive success provisional.
- **Audit the object being measured.** State what one observation, outcome,
  position, and return denominator mean. Before an economic claim, reconcile
  a simplified proxy with the relevant cash flows or another independently
  constructed measurement. More tests on the same proxy cannot repair what
  that proxy omits.
- **Investigate contradictions.** Check alignment, units, accounting, data
  revisions, and implementation before changing the economic explanation.
  Use distributions, time plots, and representative and extreme cases to
  locate the discrepancy. Keep plausible economic alternatives open; a
  surprising result is not automatically a bug.
- **Keep implementation simpler than the explanation.** Start with an
  interpretable baseline. Added complexity must demonstrate incremental value
  against it. A parameter chosen at a search boundary or an isolated winning
  subgroup calls for investigation, not immediate adoption.
- **Separate hypothesis generation from validation.** Patterns discovered during
  analysis can motivate hypotheses, but the observations that suggested them
  are not independent confirmation. State testable implications and evaluate
  generalization using evidence not used to formulate or select the hypothesis.
  Without that evidence, keep the conclusion exploratory.
- **Match conclusions to the evidence.** Ordering, calibration, average payoff,
  tail risk, and executable portfolio returns answer different questions.
  Count independent economic observations rather than generated rows. Retain
  negative and inconclusive results and limitations that affect the decision.
- **Implement the tested behavior exactly.** Changes in eligibility, timing,
  sizing, accounting, costs, or constraints create a new variant. Verify parity
  between the tested and intended paths on matched inputs before claiming
  that the existing evidence applies. A theoretical extrapolation needs a test.

Use the following references when the task calls for them; load the relevant
ones rather than the entire method library at every session:

| Task | Guidance |
| --- | --- |
| Design or revise an empirical study; decide whether to continue | [Experiment design](references/experiment-design.md) |
| Validate data, outcomes, execution assumptions, or statistical evidence | [Measurement and validation](references/measurement-validation.md) |
| Evaluate historical features or judgments produced by a language model | [Model-assisted measurement](references/model-measurement.md) |
| Write a plan, finding, correction, decision, or continuation summary | [Research records](references/research-records.md) |

## Research process

Use the project's brief and the user's request to choose a bounded question.
For an empirical study, state the hypothesis, plausible mechanism, baseline,
data and feature timing, evaluation periods, costs, measurements, rejection
criteria, and experiment budget. Scale this detail to the question. Diagnostic
work and literature investigations may need a different plan.

Separate measurement repair, exploratory diagnosis, and evaluation of a frozen
candidate. Label data already consulted by this or an earlier study as inspected.
Choose the relevant checks from the method references; do not manufacture a
universal significance threshold or a fixed battery for every research question.

Create a study with `nullfield study create --session UUID --title 'QUESTION' --file
/absolute/plan.md`. Plans are editable Markdown; each recorded run freezes a
copy of the plan as it existed before execution. A frozen copy records timing;
it does not prove an untouched holdout or prevent access to data.

Prefer experiments that distinguish explanations. Track variants and changes
prompted by observed outcomes. A reused evaluation period remains inspected
across sessions and studies; the project's evaluation-data ledger records it.
Investigate coding, alignment, and cost assumptions before treating a
surprising metric as economic evidence.

Use the host's normal coding and analysis tools. When running an experiment,
record it through:

```bash
nullfield run start --session UUID --study STUDY_UUID --cwd /absolute/code/path \
  --timeout 300 --input experiment.py --input data.csv -- python experiment.py
```

Use an appropriate budget; inputs are resolved against `--cwd`. All nullfield options
precede `--`; the remaining arguments are executed directly, without a shell.
The result contains the run UUID and paths to stdout, stderr, metadata, and the
frozen plan. A nonzero CLI exit still leaves a run record. Read the output files
to assess the result. A completed process is not a validated research finding.

For anything that may outlast one tool call, start the run with `--detach`
and a realistic `--timeout`, then `nullfield run wait --session UUID RUN_UUID
--timeout SECONDS` with a timeout below your tool-call limit, repeating while it
exits 3 (still running). Report launched-but-unfinished runs as running, never
as results. Use `nullfield run stop` to abandon one; a `lost` run's runner died
and its output is incomplete.

Declare what the command writes with `--output PATH` (repeatable); results are
fingerprinted after the run and small files are copied into the run record, so
cite `run:UUID` rather than a bare output path. Check `stderr_summary` in
`run read` before trusting a result: tracebacks and repeated warnings show up
there. The runner records Git heads, tracked text patches, and fingerprints of
changed binary files, but does not archive untracked code, dependencies, or
datasets. Add important files as `--input` to fingerprint them; preserve source
artifacts separately when reproduction requires it. Record IDs accept unique
prefixes of 8 or more characters.

## Preregistration

Freeze a study's plan with `nullfield study freeze --session UUID STUDY_UUID`
before its first evaluation on holdout data, and before looking at any
outcome the plan's decision depends on. After freezing, change the plan only
by editing `plan.md` and freezing again with `--note` stating what changed,
why, and which results were visible; this records an amendment and never
overwrites the earlier version. Check `plan_status` in `study read`: a
`drifted` plan has unrecorded edits. The ledger refuses a holdout evaluation
without a frozen, unchanged plan. Do not freeze a plan to get past that
refusal after results were seen; record an amendment that says so.

## Evaluation-data ledger

Before planning, read the evaluation samples in `context` and run
`nullfield sample show NAME` for each sample the study might use. The plan
names the samples it will use, each one's purpose (`fit`, `select`, `evaluate`,
`inspect`), and what they have already been used for. Define missing samples
with `nullfield sample define` rather than describing periods only in prose.

Record every use when it happens: `--sample NAME:PURPOSE` on `run start`, or
`nullfield sample use` for work outside the runner (with `--date` when
backfilling history). Examining a sample's outcomes to make a research choice
is a use even when no code runs. If the ledger refuses a use, stop and
report the conflict to the user; pass `--acknowledge-conflicts` only when the
user accepts that the result uses previously seen data, and label it so in
every resulting entry. Never define a new sample to avoid a recorded use.

## Notebook operations

```bash
nullfield sample define --session UUID holdout --dataset labels --start 2014-01-01 --role holdout
nullfield sample show --session UUID holdout
nullfield sample use --session UUID holdout --purpose inspect --study STUDY_UUID
nullfield resource add --session UUID pricing /absolute/pricing --kind repo --description 'Pricing implementation'
nullfield search --session UUID 'transaction costs'
nullfield study list --session UUID
nullfield study read --session UUID STUDY_UUID
nullfield entry read --session UUID ENTRY_UUID
nullfield run read --session UUID RUN_UUID
nullfield entry add --session UUID --study STUDY_UUID --kind decision \
  --title 'Stop: the effect does not survive costs' --file /absolute/decision.md --study-state concluded
nullfield entry add --session UUID --study STUDY_UUID --kind finding \
  --title 'Improvement disappears at observed spreads' --file /absolute/finding.md \
  --evidence run:RUN_UUID
```

Entry kinds are `observation`, `finding`, `decision`, `question`, and `issue`. Findings
require evidence references: `run:UUID`, `entry:UUID`, an existing file, or a URL.
Evidence validation checks references, not whether they justify a claim.
Represent inconclusive and negative results explicitly. State each finding's
scope, assumptions, uncertainty, and contrary evidence in its Markdown body.

Record a correction, reversal, or answer as a new entry with `--supersedes
ENTRY_UUID`; the earlier entry stays unchanged and is reported as superseded in
`read`, `list`, `search`, and `context`. Supersede only an entry the new one
replaces as the current word; cite supporting entries with `--evidence`
instead. Before relying on a retrieved entry, check `superseded_by`, and
check `stale_evidence` for superseded entries its evidence rests on; revisit
or supersede a conclusion whose evidence was corrected. Link to
another project's evidence by file or URL and preserve its original scope;
don't silently copy its conclusions into this project as established facts.

When you find a bug or a data problem, record an `issue` before fixing it:
`nullfield entry add --session UUID --kind issue --title '...' --file /absolute/issue.md
--affects commit:SHA` (or `sha:HEX` for a file's digest, `run:ID`, `entry:ID`;
repeatable). The result lists the runs and entries it questions; use it to
scope the problem and state it in the issue. Check `questioned_by` before
relying on any run or entry. A finding citing questioned evidence is refused;
pass `--acknowledge-issues` only when the finding explains why the issue does
not change it. Resolve an issue by superseding it with what was checked or
rerun, and supersede the affected findings with corrected ones.

Finish a substantial investigation with a decision entry explaining what changed,
what remains uncertain, and the next action or reason to stop. Pass
`--study STUDY_UUID --study-state concluded` (or `abandoned`, or `open` to
reopen) so the study's state follows the decision. A decision that supersedes
a state-setting decision must restate the state. Let the user's objective and
budget determine whether to continue autonomously.

## Sessions and continuation

Research-session IDs belong to nullfield, not to the host's native session system.
They persist in the registry, but this MVP does not install lifecycle hooks.
Carry the UUID in handoff summaries. If unavailable, ask for the project or
session, or use the explicit project in the user's request to start a new one.
Switching projects creates a new research session; other sessions are unaffected.
For direct scripted operations, `--project ALIAS` can replace `--session UUID`.

## Shared methods and private research

Keep reusable methods in the skill and project-specific economic hypotheses,
signals, universes, parameters, results, and operational details in that
project's private notebook. Reading private research does not authorize
publishing it in a shared skill. Generalize the reasoning without preserving
a reconstructable trading recipe. Use independently constructed examples;
check filenames, links, logs, and artifact metadata as well as prose before
moving material into a public repository.
