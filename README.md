# nullfield

**A research notebook for coding agents.**

nullfield gives Claude Code and Codex a durable record of what was tried, what was
found, and which data has already been looked at. It also refuses to let a study
quietly reuse a holdout.

Python 3.11+ · no runtime dependencies · local files, no server · MIT

> **Status:** early (v0.1). The CLI and notebook format may still change.

## Why

Coding agents make research fast. They also speed up the ways research goes wrong:

- **They forget.** A new session doesn't know which ideas already failed, so dead ends get retried.
- **They reuse evaluation data.** Every "quick check" on the holdout spends it, and after a
  few sessions the out-of-sample result isn't out of sample.
- **They lose provenance.** A number in a chat log can't be traced to the code, inputs, and
  plan that produced it.
- **Corrections don't propagate.** A withdrawn result keeps getting cited because nothing
  marks it as withdrawn.

nullfield is the record your agent keeps: projects, pre-registered studies, recorded runs,
and findings linked to their evidence, plus a ledger of every look at evaluation data. The
agent still does the research. nullfield makes it remember, cite, and account for its data.

## Highlights

- **Persistent notebook.** Studies, findings, decisions, and open questions survive across
  sessions and agents, and `context` gives any new session the current state.
- **Preregistration.** Freeze a study's plan before evaluating. Later changes are amendments
  that say what changed and which results had been seen.
- **Evaluation-data ledger.** Every use of a sample is recorded by purpose (fit, select,
  evaluate, inspect). Reusing a holdout, or evaluating without a frozen plan, is refused
  until you acknowledge it.
- **Run provenance.** `run start` records the command, Git state, input and output
  fingerprints, and the plan version. `--detach` covers runs that take hours.
- **Corrections that stick.** A new entry can supersede an old one. Search and context
  then show the old result as superseded, flag every entry whose evidence rests on it,
  and nothing is rewritten.
- **A research skill for your agent.** One command installs the workflow and methods
  guidance into Claude Code or Codex.

## Install

```bash
uv tool install git+https://github.com/Implied-Capital/nullfield   # or: pipx install git+...
nullfield skills install --agent claude                             # or: codex, both
```

## Use it with your agent

Create a project once, then hand the agent a question:

```bash
nullfield project create momentum --name "Momentum costs" \
  --objective "Decide whether the signal survives realistic costs."
```

```text
/research momentum does a volatility filter rescue the signal?     # Claude Code
$research momentum does a volatility filter rescue the signal?     # Codex
```

The skill has the agent:
1. Read the project's context and search earlier findings, including negative ones.
2. Write a plan and freeze it before any evaluation.
3. Run experiments through `nullfield run start` with declared samples and outputs.
4. Record findings with evidence, supersede any results that turn out wrong, and close the
   study with a decision.

Your prompt only has to name the project and the question.

## Walkthrough

The same workflow by hand. Output is trimmed.

```console
$ nullfield sample define --project momentum train   --dataset prices --start 2010-01-01 --end 2013-12-31 --role development
$ nullfield sample define --project momentum holdout --dataset prices --start 2014-01-01 --end 2016-12-31 --role holdout
$ nullfield study create --project momentum --title "Does the signal survive costs?" --file plan.md
{"id": "29138de6-c0dd-4181-a26e-ed4462888668", ...}

$ nullfield run start --project momentum --study 29138de6 --cwd code --sample holdout:evaluate -- python backtest.py
nullfield: Recording evaluate on sample holdout conflicts with the ledger:
- evaluating holdout (holdout: holdout): study 'Does the signal survive costs?' had no frozen plan by 2026-09-23; run 'nullfield study freeze' first
Nothing was recorded. ...

$ nullfield study freeze --project momentum 29138de6
{"kind": "freeze", "plan_sha256": "c69df02f0032...", ...}

$ nullfield run start --project momentum --study 29138de6 --cwd code \
    --sample train:fit --sample holdout:evaluate --output results -- python backtest.py
{"id": "e0c9134f-...", "status": "completed",
 "outputs": [{"path": "results/summary.json", "sha256": "d49e945e4959...", "kept": "outputs/results/summary.json"}], ...}

$ nullfield entry add --project momentum --study 29138de6 --kind finding \
    --title "Net edge of 2.1 bps/trade misses the 3 bps bar" --body "Holdout 2014-2016, one evaluation." --evidence run:e0c9134f
$ nullfield entry add --project momentum --study 29138de6 --kind decision \
    --title "Stop: the edge does not survive costs" --body "Reopen only with a cheaper execution model." --study-state concluded
```

IDs accept any unique prefix of 8 or more characters. Every record is plain Markdown or
JSON in the project's notebook directory.

## The ledger says no

Later, a new study wants to try a filtered variant on the same holdout:

```console
$ nullfield run start --project momentum --study 736a3fe6 --cwd code --sample holdout:evaluate -- python backtest.py
nullfield: Recording evaluate on sample holdout conflicts with the ledger:
- prior use 8dbc33e2-...: evaluate on 2026-09-23 by study 'Does the signal survive costs?' (29138de6-...)
Nothing was recorded. If this use is intended, rerun with --acknowledge-conflicts and label the result as using previously seen data.
```

The run doesn't start and nothing is written. If you do want to reuse the holdout,
`--acknowledge-conflicts` records the use along with the conflict, so anyone reading the
result later knows the data had already been seen. Samples of the same dataset share
history when their dates overlap, so defining a new window around an old holdout doesn't
reset it.

## Concepts

| Concept | What it is |
| --- | --- |
| **Project** | A research agenda, not a repository. It can reference several repos, datasets, and papers. |
| **Study** | One bounded question with a Markdown plan. It's `open` until a decision concludes or abandons it. |
| **Freeze** | A timestamped, hashed copy of the plan. The first freeze is the preregistration; later ones are amendments. |
| **Run** | A recorded command: Git state, input and output fingerprints, the plan copy, logs, and status. |
| **Entry** | A `finding`, `decision`, `observation`, or `question`. Findings must cite evidence, and any entry can supersede an earlier one. |
| **Sample / use** | A named slice of evaluation data, plus every recorded look at it and why. |

A notebook is a directory of plain files that you can commit to a private Git repository.
A small SQLite registry holds only local aliases, paths, and sessions.

## How it compares

- **Experiment trackers (MLflow, Weights & Biases)** log parameters, metrics, and models
  for each run. nullfield records the reasoning around the runs: plans, findings,
  corrections, and which data each conclusion used. You can use both and cite the run in
  nullfield.
- **Data versioning (DVC)** stores and versions datasets and pipelines. nullfield never
  copies datasets. It fingerprints inputs and outputs and tracks how evaluation data has been
  used.
- **Notes and agent memory files** don't link claims to evidence, don't mark corrections,
  and don't stop anyone from reusing a holdout.

## Documentation

- **[Guide](docs/guide.md):** every command and option, sessions, detached runs, ledger
  rules, the on-disk format, and moving notebooks between machines.
- **[The research skill](src/nullfield/skills/research/SKILL.md)** and its method
  references, which cover experiment design, measurement and validation, model-assisted
  measurement, and research records.

## FAQ

**Does it need a server or an account?** No. It runs on local files and a local SQLite
registry, with no runtime dependencies.

**Do I need an agent?** No. The CLI works on its own. The skill is how Claude Code and
Codex use it.

**Does it store my data?** No. Datasets stay where they are. nullfield stores
fingerprints, plans, logs, and declared output files under a size budget (5 MB per run by
default).

**Can it stop an agent from cheating?** It records every declared use of data and
refuses conflicting ones. It can't detect data read without a declaration. It is a
guardrail and an audit trail, not a sandbox.

## Develop

```bash
git clone https://github.com/Implied-Capital/nullfield && cd nullfield
python -m venv .venv && source .venv/bin/activate && pip install -e .
python -m unittest discover -s tests
python examples/demo.py      # disposable projects; touches no real data or registry
```

## License

MIT
