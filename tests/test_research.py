from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from nullfield.experiments import prepare_run, run_experiment, stop_run, wait_run
from nullfield.integration import install_skill
from nullfield.ledger import define_sample, get_sample, list_samples, record_use, show_sample, today
from nullfield.store import (ResearchError, Store, add_entry, annotate, context,
                                 create_study, freeze_study, get_record, list_records, search)


class ResearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "registry"
        self.store = Store(self.home)
        self.alpha = self.store.create_project("alpha", "Alpha research", self.root / "alpha", "Test a signal.")
        self.beta = self.store.create_project("beta", "Beta research", self.root / "beta", "Measure costs.")

    def tearDown(self):
        self.store.close()
        self.temporary.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, "-m", "nullfield", "--home", str(self.home), *args],
                              text=True, capture_output=True, timeout=20)

    def test_shared_repo_independent_sessions_and_memory(self):
        repo = self.root / "shared-repo"
        repo.mkdir()
        for project in (self.alpha, self.beta):
            self.store.add_resource(project, "code", str(repo), "repo", "Shared implementation")
        a = self.store.start_session(self.alpha, "codex")
        b = self.store.start_session(self.beta, "claude")
        add_entry(self.store.scope(None, a["id"]), "observation", "Alpha only", "A result", None, [])
        add_entry(self.store.scope(None, b["id"]), "observation", "Beta only", "B result", None, [])
        self.assertIn("Alpha only", context(self.store, self.alpha, a["id"]))
        self.assertNotIn("Beta only", context(self.store, self.alpha, a["id"]))
        self.assertEqual(search(self.beta, "Alpha only"), [])
        self.assertEqual(self.store.scope(None, a["id"])["id"], self.alpha["id"])

    def test_explicit_scope_required(self):
        with self.assertRaises(ResearchError):
            self.store.scope(None, None)
        with self.assertRaises(ResearchError):
            self.store.scope("alpha", self.store.start_session(self.beta, "manual")["id"])
        result = self.cli("entry", "list")
        self.assertEqual(result.returncode, 2)

    def test_session_survives_process_restart_and_project_move(self):
        session = self.store.start_session(self.alpha, "codex")
        moved = self.root / "moved-notebook"
        shutil.move(self.alpha["path"], moved)
        self.store.register_project("renamed", moved)
        other = Store(self.home)
        try:
            self.assertEqual(other.scope(None, session["id"])["path"], str(moved.resolve()))
            self.assertEqual(other.scope(None, session["id"])["alias"], "renamed")
        finally:
            other.close()

    def test_notebook_can_be_registered_on_a_different_machine(self):
        original = add_entry(self.alpha, "decision", "Stop this approach", "Costs dominate.", None, [])
        copy = self.root / "copied-notebook"
        shutil.copytree(self.alpha["path"], copy)
        other = Store(self.root / "another-registry")
        try:
            project = other.register_project("my-alias", copy)
            self.assertEqual(project["id"], self.alpha["id"])
            self.assertEqual(list_records(project, "entries")[0]["id"], original["id"])
            self.assertEqual(other.resources(project), [])
        finally:
            other.close()

    def test_duplicate_alias_does_not_create_or_overwrite_notebooks(self):
        unused = self.root / "unused"
        with self.assertRaises(ResearchError):
            self.store.create_project("alpha", "Replacement", unused, "Different objective")
        self.assertFalse(unused.exists())
        occupied = self.root / "occupied"
        occupied.mkdir()
        (occupied / "important.txt").write_text("keep me")
        with self.assertRaises(ResearchError):
            self.store.create_project("third", "Third", occupied, "Objective")
        self.assertEqual((occupied / "important.txt").read_text(), "keep me")

    def test_cross_project_links_are_rejected(self):
        study = create_study(self.alpha, "Alpha study", "Frozen plan")
        with self.assertRaises(ResearchError):
            add_entry(self.beta, "observation", "Wrong project", "Body", study["id"], [])
        entry = add_entry(self.alpha, "observation", "Alpha", "Body", None, [])
        with self.assertRaises(ResearchError):
            add_entry(self.beta, "finding", "Wrong evidence", "Body", None, [f"entry:{entry['id']}"])

    def test_finding_requires_resolvable_evidence(self):
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "finding", "Unsupported", "Body", None, [])
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "finding", "Missing file", "Body", None, [str(self.root / "missing")])
        source = add_entry(self.alpha, "observation", "Costs", "Transaction costs dominated the gain.", None, [])
        finding = add_entry(self.alpha, "finding", "Rejected", "Only under tested conditions.", None, [f"entry:{source['id']}"])
        self.assertEqual(finding["evidence"], [f"entry:{source['id']}"])
        self.assertEqual(search(self.alpha, "transaction COSTS")[0]["id"], source["id"])

    def test_search_includes_studies_and_old_negative_results(self):
        old = add_entry(self.alpha, "finding", "Rejected mean reversion", "Costs erase the effect.", None, ["https://example.org/evidence"])
        for i in range(12):
            add_entry(self.alpha, "observation", f"Unrelated {i}", "Fresh data", None, [])
        study = create_study(self.alpha, "Mean reversion retry", "Check different transaction costs.")
        matches = search(self.alpha, "mean reversion")
        self.assertEqual({r["id"] for r in matches}, {old["id"], study["id"]})
        self.assertNotIn(old["id"], context(self.store, self.alpha, None, limit=3))

    def test_concurrent_writers_do_not_lose_records(self):
        def write(i):
            local = Store(self.home)
            try:
                session = local.start_session(local.project("alpha"), "manual")
                return add_entry(local.scope(None, session["id"]), "observation", f"Parallel {i}", "Body", None, [])
            finally:
                local.close()
        with ThreadPoolExecutor(max_workers=6) as pool:
            records = list(pool.map(write, range(18)))
        self.assertEqual(len(list_records(self.alpha, "entries")), 18)
        self.assertEqual(len({r["id"] for r in records}), 18)
        self.assertEqual(len(self.store.list_sessions(self.alpha)), 18)

    def test_ids_cannot_escape_record_directory(self):
        with self.assertRaises(ResearchError):
            get_record(self.alpha, "entries", "../../beta/project")

    def test_alias_cannot_shadow_another_projects_id(self):
        with self.assertRaises(ResearchError):
            self.store.register_project(self.alpha["id"], self.beta["path"])
        self.assertEqual(self.store.project(self.alpha["id"])["alias"], "alpha")

    def test_replaced_manifest_does_not_redirect_existing_session(self):
        session = self.store.start_session(self.alpha, "manual")
        shutil.copyfile(Path(self.beta["path"]) / "project.json", Path(self.alpha["path"]) / "project.json")
        with self.assertRaises(ResearchError):
            self.store.scope(None, session["id"])

    def test_experiment_preserves_plan_output_and_input_hash(self):
        study = create_study(self.alpha, "Costs", "The original protocol.")
        data = self.root / "prices.csv"
        data.write_text("price\n100\n")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "import sys; print('result=2'); print('diagnostic', file=sys.stderr)"], self.root, 10, ["prices.csv"], [])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(len(result["inputs"][0]["sha256"]), 64)
        (Path(study["path"]) / "plan.md").write_text("A changed protocol")
        self.assertEqual((Path(result["path"]) / "plan.md").read_text(), "The original protocol.\n")
        self.assertIn("result=2", (Path(result["path"]) / "stdout.log").read_text())
        self.assertIn("diagnostic", (Path(result["path"]) / "stderr.log").read_text())
        finding = add_entry(self.alpha, "finding", "Recorded", "Scope", study["id"], [f"run:{result['id']}"])
        self.assertEqual(finding["study_id"], study["id"])

    def test_failed_and_missing_commands_are_recorded(self):
        study = create_study(self.alpha, "Failure", "Expect an error")
        failed = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "raise SystemExit(7)"], self.root, 10, [], [])
        missing = run_experiment(self.alpha, study["id"], [str(self.root / "does-not-exist")], self.root, 10, [], [])
        self.assertEqual((failed["status"], failed["returncode"]), ("failed", 7))
        self.assertEqual((missing["status"], missing["returncode"]), ("failed", 127))
        self.assertEqual(len(list_records(self.alpha, "runs")), 2)

    def test_timeout_is_terminal_and_does_not_leave_evidence_running(self):
        study = create_study(self.alpha, "Timeout", "Time budget one second")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "import time; time.sleep(30)"], self.root, 1, [], [])
        saved = get_record(self.alpha, "runs", result["id"])
        self.assertEqual((saved["status"], saved["returncode"]), ("timed_out", 124))
        self.assertIsNotNone(saved["finished_at"])

    def test_detached_run_is_finalized_by_its_supervisor(self):
        define_sample(self.alpha, "train", "labels", "2010-01-01", "2013-12-31", "development", "")
        study = create_study(self.alpha, "Background", "Long replay")
        started = time.monotonic()
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "import time; time.sleep(1); print('done=1')"],
                                self.root, 30, [], [], [("train", "fit")], detach=True)
        self.assertLess(time.monotonic() - started, 1, "Detached start must not wait for the command")
        self.assertEqual(result["status"], "running")
        self.assertNotEqual(result["runner_pid"], os.getpid())
        self.assertEqual(len(result["sample_uses"]), 1)
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "finding", "Too early", "Body", study["id"], [f"run:{result['id']}"])
        finished = wait_run(self.alpha, result["id"], 20)
        self.assertEqual((finished["state"], finished["returncode"]), ("completed", 0))
        self.assertIn("done=1", (Path(result["path"]) / "stdout.log").read_text())
        add_entry(self.alpha, "finding", "Recorded", "Body", study["id"], [f"run:{result['id']}"])

    def test_detached_timeout_and_stop_clean_up_the_command(self):
        study = create_study(self.alpha, "Budget", "Bounded")
        timed = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "import time; time.sleep(30)"],
                               self.root, 1, [], [], detach=True)
        self.assertEqual(wait_run(self.alpha, timed["id"], 20)["state"], "timed_out")
        marker = self.root / "survived"
        child = f"import time; from pathlib import Path; time.sleep(3); Path({str(marker)!r}).write_text('x')"
        running = run_experiment(self.alpha, study["id"], [sys.executable, "-c", child], self.root, 60, [], [], detach=True)
        self.assertEqual(wait_run(self.alpha, running["id"], 0.5)["state"], "running")
        stopped = stop_run(self.alpha, running["id"])
        self.assertEqual((stopped["state"], stopped["returncode"]), ("stopped", 143))
        time.sleep(3.5)
        self.assertFalse(marker.exists(), "Stopped command kept running")
        with self.assertRaisesRegex(ResearchError, "not running"):
            stop_run(self.alpha, running["id"])

    def test_run_whose_runner_died_is_reported_lost(self):
        study = create_study(self.alpha, "Crash", "Runner dies")
        path = prepare_run(self.alpha, study["id"], [sys.executable, "-c", "pass"], self.root, 10, [], [], [], False)
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        record = json.loads((path / "record.json").read_text())
        record["runner_pid"] = dead.pid
        (path / "record.json").write_text(json.dumps(record))
        self.assertEqual(wait_run(self.alpha, record["id"], 1)["state"], "lost")
        self.assertIn(f"{record['id']} [lost]", context(self.store, self.alpha, None))
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "finding", "Lost evidence", "Body", study["id"], [f"run:{record['id']}"])

    def test_cli_detach_wait_and_stop_exit_codes(self):
        study = create_study(self.alpha, "CLI", "Background")
        start = self.cli("run", "start", "--project", "alpha", "--study", study["id"], "--cwd", str(self.root),
                         "--detach", "--timeout", "60", "--", sys.executable, "-c", "import time; time.sleep(30)")
        self.assertEqual(start.returncode, 0, start.stderr)
        run_id = json.loads(start.stdout)["id"]
        self.assertEqual(self.cli("run", "wait", "--project", "alpha", run_id, "--timeout", "1").returncode, 3)
        self.assertEqual(self.cli("run", "stop", "--project", "alpha", run_id).returncode, 0)
        self.assertEqual(self.cli("run", "wait", "--project", "alpha", run_id).returncode, 143)
        # A foreground run is stopped through its own nullfield process.
        foreground = subprocess.Popen([sys.executable, "-m", "nullfield", "--home", str(self.home), "run", "start",
                                       "--project", "alpha", "--study", study["id"], "--cwd", str(self.root), "--",
                                       sys.executable, "-c", "import time; time.sleep(30)"],
                                      stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            live = [r for r in list_records(self.alpha, "runs") if r["id"] != run_id and r.get("pid")]
            if live:
                break
            time.sleep(0.1)
        stop_run(self.alpha, live[0]["id"])
        foreground.communicate(timeout=20)
        self.assertEqual(foreground.returncode, 143)
        self.assertEqual(get_record(self.alpha, "runs", live[0]["id"])["status"], "stopped")

    def test_cli_failed_run_propagates_exit_code_and_json(self):
        study = create_study(self.alpha, "Failure", "Exit nonzero")
        result = self.cli("run", "start", "--project", "alpha", "--study", study["id"], "--cwd", str(self.root),
                          "--", sys.executable, "-c", "raise SystemExit(6)")
        self.assertEqual(result.returncode, 6, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")

    @unittest.skipUnless(os.name == "posix", "Process groups require POSIX")
    def test_timeout_kills_child_even_when_leader_exits(self):
        study = create_study(self.alpha, "Child cleanup", "Enforce the time budget")
        marker = self.root / "escaped-child"
        pidfile = self.root / "child.pid"
        child = ("import os, signal, time; from pathlib import Path; "
                 "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                 f"Path({str(pidfile)!r}).write_text(str(os.getpid())); "
                 f"time.sleep(2); Path({str(marker)!r}).write_text('escaped')")
        parent = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
        try:
            result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", parent], self.root, 1, [], [])
            self.assertEqual(result["status"], "timed_out")
            self.assertTrue(pidfile.exists(), "Child did not start")
            time.sleep(1.5)
            self.assertFalse(marker.exists(), "Child outlived the timed-out experiment")
        finally:
            if pidfile.exists():
                try:
                    os.kill(int(pidfile.read_text()), signal.SIGKILL)
                except ProcessLookupError:
                    pass

    @unittest.skipUnless(shutil.which("git"), "Git is not installed")
    def test_multi_repo_provenance_captures_tracked_changes(self):
        resources = []
        for name in ("one", "two"):
            repo = self.root / name
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "model.py").write_text("baseline = 1\n")
            subprocess.run(["git", "-C", str(repo), "add", "model.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.org", "-c", "commit.gpgsign=false", "commit", "-qm", "baseline"], check=True)
            (repo / "model.py").write_text(f"baseline = {2 if name == 'one' else 3}\n")
            # A legitimate resource named 'cwd' must not overwrite the cwd patch.
            resources.append({"name": "cwd" if name == "two" else name, "kind": "repo", "location": str(repo)})
        study = create_study(self.alpha, "Multiple repos", "Compare implementations")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "pass"], self.root / "one", 10, [], resources)
        self.assertEqual(len(result["code"]), 2)
        self.assertEqual(len({code["tracked_patch"] for code in result["code"]}), 2)
        for code in result["code"]:
            self.assertEqual(len(code["commit"]), 40)
            expected = 2 if Path(code["root"]).name == "one" else 3
            self.assertIn(f"+baseline = {expected}", (Path(result["path"]) / code["tracked_patch"]).read_text())

    def test_supersession_is_recorded_on_the_new_entry_and_derived_for_the_old(self):
        original = add_entry(self.alpha, "finding", "Signal A hit rate 0.61", "Informal note.", None, ["https://example.org/a"])
        note = Path(original["path"]) / "note.md"
        before = (note.read_bytes(), (Path(original["path"]) / "record.json").read_bytes())
        correction = add_entry(self.alpha, "finding", "Signal A hit rate is 0.58", "Corrected.", None,
                               [f"entry:{original['id']}"], [f"entry:{original['id']}", original["id"]])
        self.assertEqual(correction["supersedes"], [original["id"]])
        self.assertEqual(before, (note.read_bytes(), (Path(original["path"]) / "record.json").read_bytes()),
                         "Superseding must not rewrite the earlier entry")
        [found] = [r for r in search(self.alpha, "0.61") if r["id"] == original["id"]]
        self.assertEqual(found["superseded_by"], [correction["id"]])
        self.assertIn(f"[finding; superseded by {correction['id']}] Signal A hit rate 0.61", context(self.store, self.alpha, None))
        read = json.loads(self.cli("entry", "read", "--project", "alpha", original["id"]).stdout)
        self.assertEqual(read["superseded_by"], [correction["id"]])
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "observation", "Bad link", "Body", None, [], [str(uuid.uuid4())])
        other = add_entry(self.beta, "observation", "Beta note", "Body", None, [])
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "observation", "Cross-project", "Body", None, [], [other["id"]])

    def test_entries_citing_superseded_evidence_are_reported_through_the_citation_chain(self):
        base = add_entry(self.alpha, "finding", "Spread is 1.2 bps", "Measured.", None, ["https://example.org/s"])
        net = add_entry(self.alpha, "finding", "Net edge 2.1 bps", "Uses the spread.", None, [f"entry:{base['id']}"])
        decision = add_entry(self.alpha, "decision", "Stop the signal", "Edge too small.", None, [f"entry:{net['id']}"])
        unrelated = add_entry(self.alpha, "finding", "Turnover 40%", "Measured.", None, ["https://example.org/t"])
        [clean] = annotate(self.alpha, "entries", [get_record(self.alpha, "entries", decision["id"])])
        self.assertEqual(clean["stale_evidence"], [])

        fix = add_entry(self.alpha, "finding", "Spread is 1.9 bps", "Corrected.", None,
                        [f"entry:{base['id']}"], [base["id"]])
        stale = {r["id"]: r["stale_evidence"] for r in annotate(self.alpha, "entries", list_records(self.alpha, "entries"))}
        self.assertEqual(stale[net["id"]], [{"entry": base["id"], "superseded_by": [fix["id"]], "via": []}])
        self.assertEqual(stale[decision["id"]], [{"entry": base["id"], "superseded_by": [fix["id"]], "via": [net["id"]]}])
        self.assertEqual(stale[fix["id"]], [], "The correction cites what it replaces")
        self.assertEqual(stale[unrelated["id"]], [])
        text = context(self.store, self.alpha, None)
        self.assertIn("## Entries citing superseded evidence (all 2)", text)
        self.assertIn(f"- {decision['id']} [decision] Stop the signal — cites {base['id']} superseded by {fix['id']} "
                      f"(via {net['id']})", text)
        self.assertIn(f"[decision; cites superseded evidence] Stop the signal", text)

        # Once the chain is corrected, only entries still resting on the old value are reported.
        net_fix = add_entry(self.alpha, "finding", "Net edge 1.4 bps", "Recomputed.", None,
                            [f"entry:{fix['id']}", f"entry:{net['id']}"], [net["id"]])
        stale = {r["id"]: r["stale_evidence"] for r in annotate(self.alpha, "entries", list_records(self.alpha, "entries"))}
        self.assertEqual(stale[net_fix["id"]], [])
        self.assertEqual(stale[decision["id"]], [{"entry": net["id"], "superseded_by": [net_fix["id"]], "via": []}],
                         "The search stops at a superseded entry")
        text = context(self.store, self.alpha, None)
        self.assertIn("## Entries citing superseded evidence (all 1)", text)
        read = json.loads(self.cli("entry", "read", "--project", "alpha", decision["id"]).stdout)
        self.assertEqual(read["stale_evidence"][0]["entry"], net["id"])
        [found] = [r for r in search(self.alpha, "signal") if r["id"] == decision["id"]]
        self.assertEqual(found["stale_evidence"][0]["superseded_by"], [net_fix["id"]])

    def test_study_state_is_set_by_decisions_and_open_work_is_listed(self):
        study = create_study(self.alpha, "Filter rules", "Plan")
        other = create_study(self.alpha, "Momentum filter", "Plan")
        question = add_entry(self.alpha, "question", "Does the volume filter help?", "Untested.", study["id"], [])
        answered = add_entry(self.alpha, "question", "Is a 5% threshold enough?", "Unknown.", None, [])
        add_entry(self.alpha, "finding", "Threshold needs 7-9%", "Measured.", None, ["https://example.org/b"], [answered["id"]])
        for i in range(12):
            add_entry(self.alpha, "observation", f"Filler {i}", "Body", None, [])
        text = context(self.store, self.alpha, None, limit=3)
        self.assertIn("## Open studies (all 2)", text)
        self.assertIn(question["id"], text, "Open questions are listed beyond the recent-record limit")
        self.assertNotIn(answered["id"], text.split("## Recent")[0])
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "finding", "Not a decision", "Body", study["id"], ["https://example.org/c"], [], "concluded")
        with self.assertRaises(ResearchError):
            add_entry(self.alpha, "decision", "No study", "Body", None, [], [], "concluded")
        close = add_entry(self.alpha, "decision", "Stop filter rules", "Holdout failed.", study["id"], [], [], "concluded")
        [state] = annotate(self.alpha, "studies", [get_record(self.alpha, "studies", study["id"])])
        self.assertEqual((state["state"], state["decision"]), ("concluded", close["id"]))
        self.assertIn("## Open studies (all 1)", context(self.store, self.alpha, None))
        # A correction that supersedes the closing decision without restating a state reopens the study.
        add_entry(self.alpha, "decision", "Closing rationale was wrong", "Rerun needed.", study["id"], [], [close["id"]])
        [state] = annotate(self.alpha, "studies", [get_record(self.alpha, "studies", study["id"])])
        self.assertEqual(state["state"], "open")
        add_entry(self.alpha, "decision", "Abandon momentum filter", "Not deployable.", other["id"], [], [], "abandoned")
        states = {r["id"]: r["state"] for r in json.loads(self.cli("study", "list", "--project", "alpha").stdout)}
        self.assertEqual(states, {study["id"]: "open", other["id"]: "abandoned"})

    def define_eras(self):
        define_sample(self.alpha, "train", "labels", "2010-01-01", "2013-12-31", "development", "")
        define_sample(self.alpha, "holdout", "labels", "2014-01-01", "2016-12-31", "holdout", "")
        define_sample(self.alpha, "reserve", "labels", "2017-01-01", None, "holdout", "Open-ended")

    def test_samples_are_immutable_and_validated(self):
        self.define_eras()
        with self.assertRaises(ResearchError):
            define_sample(self.alpha, "holdout", "labels", "2011-01-01", None, "holdout", "Redefinition")
        with self.assertRaises(ResearchError):
            define_sample(self.alpha, "backwards", "labels", "2015-01-01", "2014-01-01", "development", "")
        with self.assertRaises(ResearchError):
            define_sample(self.alpha, "bad-date", "labels", "2015-13-01", None, "development", "")
        with self.assertRaises(ResearchError):
            get_sample(self.beta, "holdout")
        self.assertEqual([s["name"] for s in list_samples(self.alpha)], ["train", "holdout", "reserve"])

    def test_evaluating_a_used_sample_is_refused_without_acknowledgement(self):
        self.define_eras()
        selection = create_study(self.alpha, "Pick a variant", "Compare variants on the holdout.")
        confirm = create_study(self.alpha, "Confirm the variant", "Evaluate the chosen variant.")
        freeze_study(self.alpha, selection["id"], "")
        freeze_study(self.alpha, confirm["id"], "")
        first = record_use(self.alpha, "holdout", "evaluate", selection["id"], None, "", False)
        self.assertEqual(first["acknowledged_conflicts"], [])
        # The same study repeating its own evaluation is not prior use by someone else.
        record_use(self.alpha, "holdout", "evaluate", selection["id"], None, "", False)
        with self.assertRaisesRegex(ResearchError, first["id"]):
            record_use(self.alpha, "holdout", "evaluate", confirm["id"], None, "", False)
        self.assertEqual(len(list_records(self.alpha, "uses")), 2, "A refused use must not be written")
        reused = record_use(self.alpha, "holdout", "evaluate", confirm["id"], None, "", True)
        self.assertEqual(len(reused["acknowledged_conflicts"]), 2)
        self.assertIn("own: evaluate 3; latest", context(self.store, self.alpha, None))

    def test_fitting_or_inspecting_a_holdout_spends_it(self):
        self.define_eras()
        study = create_study(self.alpha, "Explore", "Look at everything.")
        with self.assertRaisesRegex(ResearchError, "holdout sample holdout"):
            record_use(self.alpha, "holdout", "inspect", study["id"], None, "", False)
        # A pooled development sample that overlaps a holdout spends it too.
        define_sample(self.alpha, "pooled", "labels", "2010-01-01", "2017-12-31", "development", "")
        with self.assertRaisesRegex(ResearchError, "holdout sample reserve, which overlaps pooled"):
            record_use(self.alpha, "pooled", "fit", study["id"], None, "", False)
        record_use(self.alpha, "train", "fit", study["id"], None, "", False)

    def test_overlapping_samples_share_history_within_a_dataset(self):
        self.define_eras()
        define_sample(self.alpha, "early-holdout", "labels", "2014-01-01", "2014-12-31", "holdout", "")
        define_sample(self.alpha, "other-data", "documents", "2014-01-01", "2014-12-31", "holdout", "")
        define_sample(self.alpha, "doc-set", "documents", None, None, "holdout", "Undated")
        study = create_study(self.alpha, "Early test", "Evaluate 2014.")
        freeze_study(self.alpha, study["id"], "")
        record_use(self.alpha, "early-holdout", "evaluate", study["id"], None, "", False)
        later = create_study(self.alpha, "Wider test", "Evaluate 2014-16.")
        freeze_study(self.alpha, later["id"], "")
        with self.assertRaisesRegex(ResearchError, "via overlapping sample early-holdout"):
            record_use(self.alpha, "holdout", "evaluate", later["id"], None, "", False)
        state = show_sample(self.alpha, "holdout")["status"]
        self.assertEqual((state["uses"], state["by_purpose"]), (0, {}))
        self.assertEqual(state["overlapping_by_purpose"], {"evaluate": 1})
        self.assertIn("holdout [holdout] labels 2014-01-01 → 2016-12-31 — own: none; "
                      f"via overlapping samples: evaluate 1; latest {today()}", context(self.store, self.alpha, None))
        self.assertEqual(show_sample(self.alpha, "reserve")["status"]["state"], "unused")
        self.assertEqual(show_sample(self.alpha, "other-data")["status"]["state"], "unused")
        record_use(self.alpha, "other-data", "evaluate", later["id"], None, "", False)
        self.assertEqual(show_sample(self.alpha, "doc-set")["status"]["state"], "unused")

    def test_backfilled_history_only_conflicts_with_earlier_uses(self):
        self.define_eras()
        late = create_study(self.alpha, "Late", "Later work")
        early = create_study(self.alpha, "Early", "Earlier work")
        # A development sample: only the ordering of backfilled uses is under test here.
        record_use(self.alpha, "train", "evaluate", late["id"], "2026-04-20", "", False)
        record_use(self.alpha, "train", "evaluate", early["id"], "2026-02-10", "", False)
        with self.assertRaises(ResearchError):
            record_use(self.alpha, "train", "evaluate", early["id"], "2099-01-01", "", False)
        with self.assertRaisesRegex(ResearchError, "needs a --note"):
            record_use(self.alpha, "train", "fit", None, None, "", False)
        self.assertIsNone(record_use(self.alpha, "train", "fit", None, None, "Legacy calibration", False)["study_id"])

    def test_run_records_sample_use_and_refusal_leaves_no_run(self):
        self.define_eras()
        study = create_study(self.alpha, "Holdout run", "Evaluate the frozen candidate.")
        freeze_study(self.alpha, study["id"], "")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "pass"], self.root, 10, [], [],
                                [("holdout", "evaluate"), ("train", "fit")])
        uses = [get_record(self.alpha, "uses", use_id) for use_id in result["sample_uses"]]
        self.assertEqual({(u["sample"], u["purpose"], u["run_id"]) for u in uses},
                         {("holdout", "evaluate", result["id"]), ("train", "fit", result["id"])})
        other = create_study(self.alpha, "Second look", "Evaluate again.")
        with self.assertRaises(ResearchError):
            run_experiment(self.alpha, other["id"], [sys.executable, "-c", "pass"], self.root, 10, [], [],
                           [("reserve", "evaluate"), ("holdout", "evaluate")])
        self.assertEqual(len(list_records(self.alpha, "runs")), 1)
        self.assertEqual(len(list_records(self.alpha, "uses")), 2, "No partial uses from a refused run")

    def test_cli_sample_commands(self):
        defined = self.cli("sample", "define", "--project", "alpha", "holdout", "--dataset", "labels",
                           "--start", "2014-01-01", "--role", "holdout")
        self.assertEqual(defined.returncode, 0, defined.stderr)
        study = create_study(self.alpha, "Check", "Plan")
        self.assertEqual(self.cli("study", "freeze", "--project", "alpha", study["id"]).returncode, 0)
        used = self.cli("sample", "use", "--project", "alpha", "holdout", "--purpose", "evaluate", "--study", study["id"])
        self.assertEqual(used.returncode, 0, used.stderr)
        again = self.cli("run", "start", "--project", "alpha", "--study", create_study(self.alpha, "Other", "Plan")["id"],
                         "--cwd", str(self.root), "--sample", "holdout:evaluate", "--", sys.executable, "-c", "pass")
        self.assertEqual(again.returncode, 1)
        self.assertIn("--acknowledge-conflicts", again.stderr)
        bad = self.cli("run", "start", "--project", "alpha", "--study", study["id"], "--cwd", str(self.root),
                       "--sample", "holdout:peek", "--", sys.executable, "-c", "pass")
        self.assertEqual(bad.returncode, 2)
        shown = json.loads(self.cli("sample", "show", "--project", "alpha", "holdout").stdout)
        self.assertEqual(shown["status"]["by_purpose"], {"evaluate": 1})

    def test_freezes_record_plan_versions_and_amendments(self):
        self.define_eras()
        study = create_study(self.alpha, "Confirmatory test", "Gates: effect > 0.20, coverage 80%.")
        [state] = annotate(self.alpha, "studies", [get_record(self.alpha, "studies", study["id"])])
        self.assertEqual((state["plan_status"], state["freezes"]), ("unfrozen", 0))
        first = freeze_study(self.alpha, study["id"], "")
        self.assertEqual((first["kind"], first["previous"], first["prior_uses"]), ("freeze", None, []))
        with self.assertRaisesRegex(ResearchError, "unchanged"):
            freeze_study(self.alpha, study["id"], "again")
        record_use(self.alpha, "train", "fit", study["id"], None, "", False)
        plan = Path(study["path"]) / "plan.md"
        plan.write_text("Gates: effect > 0.15, coverage 90%.\n")
        self.assertIn("[plan drifted] Confirmatory test", context(self.store, self.alpha, None))
        with self.assertRaisesRegex(ResearchError, "needs --note"):
            freeze_study(self.alpha, study["id"], "")
        amendment = freeze_study(self.alpha, study["id"], "Threshold lowered after development results were seen.")
        self.assertEqual((amendment["kind"], amendment["previous"]), ("amendment", first["id"]))
        self.assertEqual(len(amendment["prior_uses"]), 1, "An amendment records what the study had already seen")
        self.assertEqual((Path(first["path"]) / "plan.md").read_text(), "Gates: effect > 0.20, coverage 80%.\n")
        shown = json.loads(self.cli("study", "read", "--project", "alpha", study["id"]).stdout)
        self.assertEqual(([f["kind"] for f in shown["freeze_history"]], shown["plan_status"]), (["freeze", "amendment"], "frozen"))

    def test_holdout_evaluation_requires_a_frozen_unchanged_plan(self):
        self.define_eras()
        study = create_study(self.alpha, "Confirm", "Frozen candidate.")
        with self.assertRaisesRegex(ResearchError, "no frozen plan"):
            record_use(self.alpha, "reserve", "evaluate", study["id"], None, "", False)
        with self.assertRaisesRegex(ResearchError, "without a study"):
            record_use(self.alpha, "reserve", "evaluate", None, None, "Ad hoc look", False)
        # Development data needs no preregistration, unless it overlaps a holdout.
        record_use(self.alpha, "train", "evaluate", study["id"], None, "", False)
        define_sample(self.alpha, "pooled", "labels", "2010-01-01", "2017-12-31", "development", "")
        with self.assertRaisesRegex(ResearchError, r"pooled \(holdout: holdout, reserve\)"):
            record_use(self.alpha, "pooled", "evaluate", study["id"], None, "", False)
        freeze_study(self.alpha, study["id"], "")
        with self.assertRaisesRegex(ResearchError, "no frozen plan by 2026-01-01"):
            record_use(self.alpha, "reserve", "evaluate", study["id"], "2026-01-01", "", False)
        (Path(study["path"]) / "plan.md").write_text("Edited after freezing.\n")
        with self.assertRaisesRegex(ResearchError, "changed after its last freeze"):
            run_experiment(self.alpha, study["id"], [sys.executable, "-c", "pass"], self.root, 10, [], [],
                           [("reserve", "evaluate")])
        self.assertEqual(list_records(self.alpha, "runs"), [])
        freeze_study(self.alpha, study["id"], "Clarified wording only; no results seen.")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "pass"], self.root, 10, [], [],
                                [("reserve", "evaluate")])
        self.assertEqual(get_record(self.alpha, "uses", result["sample_uses"][0])["acknowledged_conflicts"], [])

    def test_unique_id_prefixes_resolve_and_are_stored_in_full(self):
        study = create_study(self.alpha, "Prefixes", "Plan")
        note = add_entry(self.alpha, "question", "Open item", "Body", study["id"][:8], [])
        self.assertEqual(note["study_id"], study["id"])
        answer = add_entry(self.alpha, "finding", "Answer", "Body", study["id"][:10], [f"entry:{note['id'][:8]}"],
                           [note["id"][:9]])
        self.assertEqual((answer["evidence"], answer["supersedes"]), ([f"entry:{note['id']}"], [note["id"]]))
        self.assertEqual(get_record(self.alpha, "entries", answer["id"][:8])["id"], answer["id"])
        run = run_experiment(self.alpha, study["id"][:8], [sys.executable, "-c", "pass"], self.root, 10, [], [])
        self.assertEqual(run["study_id"], study["id"])
        self.assertEqual(wait_run(self.alpha, run["id"][:8], 1)["id"], run["id"])
        for bad in ("abc", "../../beta", "ABCDEF12", note["id"][:7]):
            with self.assertRaises(ResearchError):
                get_record(self.alpha, "entries", bad)
        session = self.store.start_session(self.alpha, "manual")
        self.assertEqual(self.store.scope(None, session["id"][:8])["id"], self.alpha["id"])
        shown = json.loads(self.cli("entry", "read", "--project", "alpha", note["id"][:8]).stdout)
        self.assertEqual(shown["superseded_by"], [answer["id"]])

    def test_ambiguous_prefix_is_refused(self):
        ids = ["1234abcd-0000-4000-8000-000000000001", "1234abcd-0000-4000-8000-000000000002"]
        with patch("nullfield.store.new_id", side_effect=ids):
            add_entry(self.alpha, "observation", "One", "Body", None, [])
            add_entry(self.alpha, "observation", "Two", "Body", None, [])
        with self.assertRaisesRegex(ResearchError, "Ambiguous"):
            get_record(self.alpha, "entries", "1234abcd")
        self.assertEqual(get_record(self.alpha, "entries", "1234abcd-0000-4000-8000-000000000002")["title"], "Two")

    def test_declared_outputs_are_fingerprinted_and_small_ones_kept(self):
        study = create_study(self.alpha, "Outputs", "Plan")
        script = ("from pathlib import Path; out = Path('out'); (out / 'tables').mkdir(parents=True, exist_ok=True); "
                  "(out / 'result.json').write_text('{\"effect\": 0.1}'); "
                  "(out / 'tables' / 'big.bin').write_bytes(b'x' * 4000)")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", script], self.root, 10, [], [],
                                outputs=["out", "never-written.csv"], keep_bytes=1000)
        by_name = {Path(o["path"]).name: o for o in result["outputs"]}
        self.assertEqual(by_name["result.json"]["kept"], "outputs/out/result.json")
        self.assertEqual((Path(result["path"]) / "outputs/out/result.json").read_text(), '{"effect": 0.1}')
        self.assertIsNone(by_name["big.bin"]["kept"], "Files beyond the keep budget are fingerprinted only")
        self.assertEqual((by_name["big.bin"]["bytes"], len(by_name["big.bin"]["sha256"])), (4000, 64))
        self.assertTrue(by_name["never-written.csv"]["missing"])
        detached = run_experiment(self.alpha, study["id"], [sys.executable, "-c", script], self.root, 30, [], [],
                                  detach=True, outputs=["out/result.json"])
        finished = wait_run(self.alpha, detached["id"], 20)
        self.assertEqual(finished["outputs"][0]["kept"], "outputs/out/result.json")

    def test_stderr_summary_counts_repeats_warnings_and_tracebacks(self):
        study = create_study(self.alpha, "Noise", "Plan")
        script = ("import sys\nfor _ in range(40): print('lib.py:9: RuntimeWarning: overflow in matmul', file=sys.stderr)\n"
                  "print('one-off note', file=sys.stderr)\nraise ValueError('bad input')")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", script], self.root, 10, [], [])
        summary = result["stderr_summary"]
        self.assertTrue(summary["traceback"])
        self.assertEqual(summary["warning_lines"], 40)
        self.assertEqual(summary["most_repeated"][0], {"count": 40, "line": "lib.py:9: RuntimeWarning: overflow in matmul"})
        self.assertNotIn("one-off note", [r["line"] for r in summary["most_repeated"]])

    @unittest.skipUnless(shutil.which("git"), "Git is not installed")
    def test_binary_changes_are_fingerprinted_not_stored(self):
        repo = self.root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        (repo / "model.py").write_text("threshold = 1\n")
        (repo / "table.bin").write_bytes(bytes(range(256)) * 50)
        subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                        "-c", "commit.gpgsign=false", "commit", "-qm", "baseline"], check=True)
        (repo / "model.py").write_text("threshold = 2\n")
        (repo / "table.bin").write_bytes(bytes(reversed(range(256))) * 50)
        study = create_study(self.alpha, "Binary", "Plan")
        result = run_experiment(self.alpha, study["id"], [sys.executable, "-c", "pass"], repo, 10, [], [])
        [code] = result["code"]
        patch_text = (Path(result["path"]) / code["tracked_patch"]).read_bytes()
        self.assertIn(b"+threshold = 2", patch_text)
        self.assertNotIn(b"GIT binary patch", patch_text)
        self.assertLess(len(patch_text), 2000)
        [binary] = code["binary_changes"]
        self.assertEqual((binary["path"], binary["bytes"]), ("table.bin", 12800))
        self.assertEqual(len(binary["sha256"]), 64)

    def test_skill_installation_is_portable_and_preserves_existing_edits(self):
        target = self.root / "skills"
        installed = install_skill("codex", target)
        self.assertEqual(install_skill("claude", target), installed)
        skill = Path(installed[0])
        skill.write_text("User's custom research skill")
        with self.assertRaises(ResearchError):
            install_skill("codex", target)
        self.assertEqual(skill.read_text(), "User's custom research skill")
        install_skill("codex", target, force=True)
        self.assertNotEqual(skill.read_text(), "User's custom research skill")

    def test_installed_skill_references_are_present_and_edits_are_preserved(self):
        target = self.root / "skills"
        installed = install_skill("codex", target)
        skill = Path(installed[0])
        references = re.findall(r"\]\((references/[^)]+)\)", skill.read_text())
        self.assertTrue(references)
        for relative in references:
            reference = skill.parent / relative
            self.assertIn(str(reference), installed)
            self.assertTrue(reference.read_text().strip())
        reference = skill.parent / references[0]
        original = reference.read_text()
        reference.write_text("My local research methods")
        skill.unlink()
        custom = skill.parent / "personal-notes.md"
        custom.write_text("Keep this user's file")
        with self.assertRaises(ResearchError):
            install_skill("claude", target)
        self.assertFalse(skill.exists(), "Conflict check must precede entrypoint creation")
        self.assertEqual(reference.read_text(), "My local research methods")
        install_skill("claude", target, force=True)
        self.assertEqual(reference.read_text(), original)
        self.assertEqual(custom.read_text(), "Keep this user's file")
        self.assertTrue(skill.is_file())

    def test_both_hosts_are_checked_before_installing_either_bundle(self):
        home = self.root / "user-home"
        claude_target = home / ".claude/skills"
        installed = install_skill("claude", claude_target)
        reference = next(Path(path) for path in installed if Path(path).parent.name == "references")
        reference.write_text("Local changes")
        with patch("nullfield.integration.Path.home", return_value=home):
            with self.assertRaises(ResearchError):
                install_skill("both")
            self.assertFalse((home / ".agents").exists())
            self.assertEqual(reference.read_text(), "Local changes")
            paths = install_skill("both", force=True)
        self.assertTrue(all(Path(path).is_file() for path in paths))
        self.assertEqual(len(paths), 2 * len(installed))
        self.assertEqual((home / ".agents/skills/research/references" / reference.name).read_text(), reference.read_text())


if __name__ == "__main__":
    unittest.main()
