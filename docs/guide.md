# nullfield guide

The complete reference for the `nullfield` CLI and its notebook format. For what
nullfield is and why you would use it, start with the [README](../README.md).

- [Install](#install)
- [Create a project](#create-a-project)
- [Use your existing agent](#use-your-existing-agent)
- [Explicit session selection](#explicit-session-selection)
- [Studies, runs, and notebook entries](#studies-runs-and-notebook-entries)
- [Preregistration](#preregistration)
- [Evaluation-data ledger](#evaluation-data-ledger)
- [Storage and portability](#storage-and-portability)
- [Develop and try an isolated example](#develop-and-try-an-isolated-example)

## Install

Clone the repository and install using Python 3.11 or newer (for example, Python 3.12):

```bash
git clone https://github.com/zmccormick7/nullfield.git
cd nullfield
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
nullfield --help
```

For a globally available command, `pipx install .` or `uv tool install .` also
works. Activate the virtual environment to use `nullfield` in a terminal. The skill
installer records the absolute Python command so agents can use the same
installation even when their PATH differs. Keep that environment in place, or
reinstall the skill with `--force` after moving the installation.

## Create a project

```bash
nullfield project create momentum \
  --name 'Momentum costs' \
  --objective 'Determine whether the signal survives realistic trading costs.'
```

By default the notebook is created at `~/.nullfield/projects/momentum`.
Use `--path /absolute/notebook/location` to place it anywhere. That directory
must be new or empty. No repository initialization or code changes are required.

Attach local resources as needed:

```bash
nullfield resource add --project momentum pricing /path/to/pricing --kind repo
nullfield resource add --project momentum backtesting /path/to/backtesting --kind repo
nullfield resource add --project momentum prices /path/to/prices.parquet --kind dataset
nullfield resource add --project momentum paper https://example.org/paper --kind reference
```

Resources are named references. Adding one does not copy data, load it into an
agent, or change the host's workspace permissions. Reusing a resource name
updates its local binding. A `repo` resource should point to a Git checkout;
non-Git directories are usable but have no Git provenance snapshot.

## Use your existing agent

Install the same research skill into one or both agents:

```bash
nullfield skills install --agent both
# Or: --agent codex / --agent claude
```

This writes the shared skill with its local CLI command into `research/SKILL.md`
and its method references into `research/references/`,
under `~/.agents/skills` for Codex and
`~/.claude/skills` for Claude Code. `--target /path/to/skills` overrides the
destination for a single agent. It checks all bundled files for local changes
before writing and preserves them unless you explicitly pass `--force`.
Additional user-created files are left in place. No host configuration files are modified.

Then invoke it in your existing agent:

```text
Codex:       $research momentum
Claude Code: /research momentum
```

Ask it to continue a named study or investigate a question. The skill selects
the project, reads its brief and notebook index, searches relevant prior work,
and records experiments and conclusions. Only the matching skill body is loaded
by the host. The notebook context is an index; prior evidence is retrieved on demand.

The skill emphasizes measurement validity, competing explanations, simple
baselines, and exact agreement between tested and implemented behavior. It loads
deeper guidance when relevant:

- [Experiment design](../src/nullfield/skills/research/references/experiment-design.md):
  meaningful comparisons, evaluation exposure, bounded search, and stopping decisions.
- [Measurement and validation](../src/nullfield/skills/research/references/measurement-validation.md):
  input quality, economic accounting, executable prices, dependence, and portfolio feasibility.
- [Model-assisted measurement](../src/nullfield/skills/research/references/model-measurement.md):
  historical information boundaries, evidence selection, and controls for model evaluations.
- [Research records](../src/nullfield/skills/research/references/research-records.md):
  scoped findings, reproducible evidence, corrections, negative results, and handoffs.

These are research instructions followed by the host agent, not checks enforced
by the Python runner. Private hypotheses and strategy details belong in the
project notebook; the shared skill contains general methods.

Host integration references: [Codex skills](https://learn.chatgpt.com/docs/build-skills)
and [Claude Code skills](https://code.claude.com/docs/en/skills).

## Explicit session selection

```bash
nullfield session start momentum --agent codex
```

The JSON result contains a research-session UUID. Pass that UUID with every
subsequent operation:

```bash
nullfield context --session SESSION_UUID
nullfield search --session SESSION_UUID 'transaction costs'
nullfield session show SESSION_UUID
```

A research session has an immutable project binding. Another session can use a
different project in the same working directory. There is no global active
project, cwd inference, or implicit selection of the latest session. Direct
scripts may use `--project ALIAS` instead of `--session UUID`.

These UUIDs are **nullfield session IDs**, not native Codex/Claude session IDs. They
persist across nullfield process restarts. The skill carries them in conversation and
handoff summaries; automatic host lifecycle hooks are not part of this MVP. If
the association is lost, select a project again or explicitly choose a recorded
session with `nullfield session list`. To switch projects, start a new research session.

## Studies, runs, and notebook entries

Create a bounded study with a Markdown plan. The example is a planning template,
not evidence that any strategy works:

```bash
nullfield study create --session SESSION_UUID \
  --title 'Does the signal survive costs?' --file examples/cost-study.md
```

Use the returned study UUID to record a command:

```bash
nullfield run start --session SESSION_UUID --study STUDY_UUID \
  --cwd /path/to/backtesting --timeout 300 \
  --input experiment.py --input prices.csv -- python experiment.py
```

The command receives normal arguments, not an implicit shell. All nullfield options
must precede `--`. Input paths are relative to `--cwd`. Each run records:

- The exact command, working directory, time budget, timestamps, and exit status.
- A copy and SHA-256 digest of the study plan before execution.
- SHA-256 digests of the explicitly declared input files.
- Git heads and tracked text patches for the working directory and attached repo
  resources. Changed binary files are recorded by path, SHA-256, and size rather
  than stored, since their bytes dominate patch size.
- Separate stdout and stderr files, and a `stderr_summary`: line and warning counts,
  whether a traceback occurred, and the most repeated lines, for quick triage.
- Declared outputs (`--output PATH`, repeatable; files or directories, relative to
  `--cwd`): fingerprinted after the command finishes, with missing ones flagged.
  Output files that fit the `--keep-mb` budget (default 5) are copied into the
  run's `outputs/` directory, so small results travel with the notebook.

Failures, missing executables, interruptions, and timeouts produce run records
too. The CLI propagates the command's exit code (124 for timeout, 130 for an
interrupt, 127 for launch failure). On POSIX, timeout/interrupt cleanup targets
the command's process group. A successful process is marked `completed`; that
does not mean its scientific conclusion is validated.

Long runs can outlive the calling process. `--detach` hands the run to a
background supervisor and returns once the command has started; the supervisor
enforces `--timeout`, captures output, and finalizes the record:

```bash
nullfield run start --session SESSION_UUID --study STUDY_UUID --cwd /path/to/backtesting \
  --timeout 14400 --detach -- python replay.py
nullfield run wait --session SESSION_UUID RUN_UUID --timeout 540
nullfield run stop --session SESSION_UUID RUN_UUID
```

`run wait` exits with the command's code once it finishes, or 3 if it is still
running when `--timeout` elapses, so an agent with a bounded tool call can wait
in chunks. `run stop` terminates the command's process group (foreground or
detached) and records the run as `stopped` (exit 143). If the process that owns
a running record dies without finalizing it (a reboot, a killed supervisor),
`read`, `list`, and `context` report the run as `lost`; lost and running runs
cannot be cited as evidence. Liveness is a process-ID check, so a reused PID
can briefly hide a lost run.

Create a notebook entry after reviewing the evidence:

```bash
nullfield entry add --session SESSION_UUID --study STUDY_UUID \
  --kind finding --title 'The gain disappears under observed spreads' \
  --file finding.md --evidence run:RUN_UUID

nullfield entry add --session SESSION_UUID --study STUDY_UUID \
  --kind decision --title 'Stop this variant' \
  --body 'The tested fill assumption was too optimistic. Next: inspect execution data.' \
  --study-state concluded

nullfield entry add --session SESSION_UUID --kind finding \
  --title 'Corrected cost estimate' --file correction.md \
  --evidence run:RUN_UUID --supersedes ENTRY_UUID
```

Studies start `open`. A decision entry with `--study` and `--study-state
concluded|abandoned|open` sets the study's state; the latest decision that has
not been superseded determines it. `--supersedes` (repeatable) marks an earlier
entry as replaced by the new one: a correction replaces a finding, an answer
replaces a question. Nothing is rewritten; `read`, `list`, and `search` report
`superseded_by` for entries and `state` for studies. `context` lists every open
study and every unanswered question regardless of `--limit`.

Entry kinds: `observation`, `finding`, `decision`, `question`. Findings require
at least one evidence reference: `run:UUID`, `entry:UUID`, a file, or an HTTP(S)
URL. Run/entry IDs resolve within the selected project. External project evidence
can be referenced by file or URL, retaining its original scope in the prose.
URLs are stored without fetching. Existence checks do not establish scientific validity.

Read records with `nullfield study read`, `nullfield entry read`, or `nullfield run read`, followed by
`--session SESSION_UUID RECORD_UUID`. Each also supports `list`. Anywhere a record or
session ID is accepted, a unique prefix of at least 8 characters works too; stored
references always use the full ID. Metadata commands
emit JSON; `context` emits Markdown. `--file -` reads Markdown from stdin. Search
matches all whitespace-separated query words, case-insensitively, across complete
entry bodies and study plans. It includes older and negative results.

## Preregistration

A plan is editable until you freeze it. Freezing stores a copy and SHA-256 of
`plan.md` with the ledger uses the study had already made:

```bash
nullfield study freeze --session SESSION_UUID STUDY_UUID
# after editing plan.md:
nullfield study freeze --session SESSION_UUID STUDY_UUID \
  --note 'Lowered the effect threshold to 0.15; only development results had been seen.'
```

The first freeze is the preregistration. Every later freeze is an amendment
and needs `--note` saying what changed, why, and which results were visible;
it records the previous freeze and the study's prior ledger uses, so the
timing is checkable. Earlier versions are never overwritten. Studies report a
`plan_status`: `unfrozen`, `frozen`, or `drifted` (edited since the last freeze);
`study read` includes the `freeze_history`, and `context` shows the status of
every open study.

## Evaluation-data ledger

Looking at outcomes cannot be undone. The ledger names evaluation samples and
records every use of them, across studies, sessions, and agents, so a later
study can see what its evaluation data have already been used for.

```bash
nullfield sample define --project momentum train --dataset labels \
  --start 2010-01-01 --end 2013-12-31 --role development
nullfield sample define --project momentum holdout --dataset labels \
  --start 2014-01-01 --role holdout --description 'Reserved for frozen candidates'
```

A sample names a dataset and, optionally, a date range; omit `--start` or
`--end` for an open-ended range. Samples of the same dataset whose dates
intersect share history, so using a pooled 2010–2017 sample counts against a
2014 holdout. Undated samples (a fixed document set, for example) share history
only with themselves. Definitions are immutable: a changed boundary is a new sample.

Each use has a purpose: `fit` (estimate parameters), `select` (choose among
variants), `evaluate` (test a frozen candidate), or `inspect` (look at outcomes
for diagnosis or exploration). Record the uses of a run when starting it:

```bash
nullfield run start --session SESSION_UUID --study STUDY_UUID --cwd /path/to/backtesting \
  --sample train:fit --sample holdout:evaluate -- python experiment.py
```

Or record work done outside the runner, including history, with `--date`:

```bash
nullfield sample use --session SESSION_UUID holdout --purpose select \
  --study STUDY_UUID --date 2026-03-02
```

The ledger refuses, and records nothing, when a use would compromise a sample:

- `evaluate` on a sample (or an overlapping one) that an earlier use already
  saw. A study repeating its own evaluation is allowed and remains visible.
- `fit`, `select`, or `inspect` on a holdout, or on a sample overlapping one.
- `evaluate` on a holdout (or a sample overlapping one) by a study with no plan
  frozen by the use's date, by no study at all, or, for a use recorded today,
  by a study whose plan has drifted since its last freeze.

`--acknowledge-conflicts` records the use anyway and stores the conflicts with
it; label the result as using previously seen data. Backfilled uses only
conflict with uses dated on or before them. `nullfield sample show NAME` lists
a sample's uses, and `context` summarizes every sample's status. Run uses are
recorded before launch, because a command that starts may read outcomes even
if it fails. The ledger records declared use; it cannot detect undeclared access.

## Storage and portability

```text
project.json                 Stable UUID, name, schema version
brief.md                     Research objective and editable project guidance
studies/<uuid>/
  record.json                Identity, title, creation time
  plan.md                    Experiment plan (editable until frozen)
  freezes/<uuid>/            Frozen plan copies: preregistration and amendments
entries/<uuid>/
  record.json                Kind, study association, evidence references
  note.md                    Human-readable observations and interpretation
runs/<uuid>/
  record.json                Command, provenance, status
  plan.md                    Protocol copied before execution
  code-*.patch               Tracked Git text edits when applicable
  stdout.log / stderr.log    Experiment output
  outputs/                   Declared outputs within the --keep-mb budget
  supervisor.log             Detached runs only
samples/<name>/
  record.json                Dataset, date range, role
uses/<uuid>/
  record.json                Sample, purpose, study/run, date, acknowledged conflicts
```

Notebook files are the source of research content and can be versioned in Git.
SQLite stores only local project aliases/paths, resource bindings, and research
sessions. The registry defaults to `~/.nullfield/registry.sqlite3`; override
with `NULLFIELD_HOME` or `nullfield --home PATH ...` (before the subcommand).

To move or clone a notebook:

```bash
nullfield project register momentum /new/notebook/location
```

Registration preserves the manifest UUID. Re-registering that UUID updates its
local alias/path and existing sessions follow it. Each machine attaches its own
resource paths. Resource bindings and session IDs are machine-local; the notebook
travels independently. Absolute external evidence paths may need rebinding or
replacement with durable URLs when sharing across machines.

Records have unique directories and atomically replaced metadata files. SQLite
serializes registry writes. Separate local agents can append entries concurrently.
Record files remain editable by humans; the CLI does not rewrite old entries.
Use a new entry with `--supersedes` to replace an earlier conclusion. Simultaneous direct
edits to the same Markdown file still need normal collaboration/version control.

## Develop and try an isolated example

```bash
python -m unittest discover -s tests -v
python examples/demo.py
```

The demo creates disposable projects, binds both agents, runs a synthetic command,
records a finding, and verifies isolation. It uses no model APIs, touches no real
research data, and does not install skills or change your registry.
