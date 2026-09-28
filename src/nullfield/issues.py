"""Issues: recorded problems in code, data, runs, or entries, and the records that rest on them.

An issue entry names what it affects with selectors. A run is questioned when a selector matches
it or when it read a file that a questioned run wrote. An entry is questioned when a selector names
it or when its evidence rests on a questioned run or entry. Superseding the issue resolves it.
Nothing is rewritten: the status is derived from the records whenever they are read.
"""

from __future__ import annotations

import re
from pathlib import Path

from .store import ResearchError, get_record, list_records, superseded_by

HEX = re.compile(r"[0-9a-f]+")


def parse_selector(project: dict, value: str) -> str:
    """A normalized selector: run:UUID, entry:UUID, sha:HEX, or commit:HEX."""
    kind, _, target = value.partition(":")
    if kind == "run":
        return f"run:{get_record(project, 'runs', target)['id']}"
    if kind == "entry":
        return f"entry:{get_record(project, 'entries', target)['id']}"
    target = target.strip().lower()
    if kind == "sha" and HEX.fullmatch(target) and 12 <= len(target) <= 64:
        return f"sha:{target}"
    if kind == "commit" and HEX.fullmatch(target) and 7 <= len(target) <= 40:
        return f"commit:{target}"
    raise ResearchError(f"Unknown --affects selector: {value}. Use run:ID, entry:ID, sha:HEX (12 or more "
                        "hex characters of a file's SHA-256), or commit:SHA (7 or more hex characters).")


def run_files(run: dict, key: str) -> list[dict]:
    files = run.get(key)
    return [f for f in files if "sha256" in f] if isinstance(files, list) else []


def fingerprints(run: dict) -> list[str]:
    """Every file digest a run recorded: inputs, declared outputs, and changed binary files."""
    binaries = [b for code in run.get("code", []) for b in code.get("binary_changes", []) if "sha256" in b]
    return [f["sha256"] for f in run_files(run, "inputs") + run_files(run, "outputs") + binaries]


def tracked_changes(run: dict, code: dict) -> bool:
    patch = Path(run["path"]) / code["tracked_patch"]
    return bool(code.get("binary_changes")) or (patch.is_file() and patch.stat().st_size > 0)


def match(run: dict, selector: str) -> dict | None:
    """How a selector matches a run, or None. A commit match on edited code is marked dirty:
    the uncommitted changes may have introduced or fixed the problem."""
    kind, _, target = selector.partition(":")
    if kind == "run" and run["id"] == target:
        return {}
    if kind == "sha" and any(digest.startswith(target) for digest in fingerprints(run)):
        return {}
    if kind == "commit":
        for code in run.get("code", []):
            if (code.get("commit") or "").startswith(target):
                return {"dirty": True} if tracked_changes(run, code) else {}
    return None


def open_issues(entries: list[dict], replaced: dict[str, list[str]]) -> list[dict]:
    return [e for e in entries if e["kind"] == "issue" and e["id"] not in replaced]


def questioned(entries: list[dict], runs: list[dict], replaced: dict[str, list[str]]) -> tuple[dict, dict]:
    """Map run IDs and entry IDs to the open issues that question them.

    Each reason names the issue and the path from the record to what the issue selected (`via`).
    Output-to-input lineage and entry evidence both point backward in time, so one chronological
    pass over runs, and a memoized walk over entries, reach every dependent record.
    """
    issues = open_issues(entries, replaced)
    by_run: dict[str, list[dict]] = {}
    written: dict[str, list[tuple[str, list[dict]]]] = {}
    for run in sorted(runs, key=lambda r: (r["created_at"], r["id"])):
        found: list[dict] = []
        for issue in issues:
            for selector in issue.get("affects", []):
                how = match(run, selector)
                if how is not None:
                    found.append({"issue": issue["id"], "via": [selector], **how})
                    break
        for read in run_files(run, "inputs"):
            for producer, reasons in written.get(read["sha256"], []):
                for reason in reasons:
                    if producer != run["id"] and all(reason["issue"] != r["issue"] for r in found):
                        found.append({**reason, "via": [f"run:{producer}", *reason["via"]]})
        if found:
            by_run[run["id"]] = found
            for wrote in run_files(run, "outputs"):
                written.setdefault(wrote["sha256"], []).append((run["id"], found))

    by_id = {e["id"]: e for e in entries}
    memo: dict[str, list[dict]] = {}

    def reasons(entry: dict) -> list[dict]:
        if entry["id"] in memo:
            return memo[entry["id"]]
        memo[entry["id"]] = []
        found: list[dict] = []

        def add(reason: dict) -> None:
            # An issue does not question itself, e.g. by citing the run that exposed the problem.
            if reason["issue"] != entry["id"] and all(reason["issue"] != r["issue"] for r in found):
                found.append(reason)

        for issue in issues:
            if f"entry:{entry['id']}" in issue.get("affects", []):
                add({"issue": issue["id"], "via": [f"entry:{entry['id']}"]})
        for ref in entry.get("evidence", []):
            kind, _, target = ref.partition(":")
            if kind == "run":
                for reason in by_run.get(target, []):
                    add({**reason, "via": [ref, *reason["via"]]})
            # A superseded entry is reported as stale evidence instead; its replacement is what counts.
            elif kind == "entry" and target in by_id and target not in replaced:
                for reason in reasons(by_id[target]):
                    add({**reason, "via": [ref, *reason["via"]]})
        memo[entry["id"]] = found
        return found

    by_entry = {e["id"]: found for e in entries if (found := reasons(e))}
    return by_run, by_entry


def questioned_evidence(project: dict, evidence: list[str], exempt: list[str]) -> list[dict]:
    """The run and entry references in `evidence` that open issues question, except exempt entries."""
    entries = list_records(project, "entries")
    by_run, by_entry = questioned(entries, list_records(project, "runs"), superseded_by(entries))
    flagged = []
    for ref in evidence:
        kind, _, target = ref.partition(":")
        if kind == "entry" and target in exempt:
            continue
        reasons = by_run.get(target, []) if kind == "run" else by_entry.get(target, []) if kind == "entry" else []
        if reasons:
            flagged.append({"evidence": ref, "issues": sorted({r["issue"] for r in reasons})})
    return flagged
