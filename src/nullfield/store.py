"""Portable project files, with machine-local registration in SQLite."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path


class ResearchError(Exception):
    """An actionable user-facing error."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id() -> str:
    return str(uuid.uuid4())


def checked_id(value: str) -> str:
    try:
        if str(uuid.UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError):
        raise ResearchError(f"Invalid ID: {value}") from None
    return value


def alias_name(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ResearchError("Names must be 1–64 lowercase letters, numbers, hyphens or underscores.")
    try:
        uuid.UUID(value)
    except ValueError:
        pass
    else:
        raise ResearchError("UUIDs are reserved for record identities; choose a descriptive name.")
    return value


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ResearchError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ResearchError(f"Expected a JSON object in {path}")
    return value


def atomic_text(path: Path, text: str) -> None:
    """Replace one file atomically; each notebook record has its own unique path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".nullfield-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_json(path: Path, data: dict) -> None:
    atomic_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


class Store:
    def __init__(self, home: Path | str | None = None):
        self.home = Path(home or os.environ.get("NULLFIELD_HOME", "~/.nullfield")).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.home / "registry.sqlite3", timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, alias TEXT UNIQUE NOT NULL, path TEXT UNIQUE NOT NULL
            );
            CREATE TABLE IF NOT EXISTS resources (
                project_id TEXT NOT NULL REFERENCES projects(id),
                name TEXT NOT NULL, kind TEXT NOT NULL, location TEXT NOT NULL,
                description TEXT NOT NULL, PRIMARY KEY(project_id, name)
            );
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                agent TEXT NOT NULL, created_at TEXT NOT NULL
            );
        """)

    def close(self) -> None:
        self.db.close()

    def create_project(self, alias: str, name: str, root: Path | str | None, objective: str) -> dict:
        alias_name(alias)
        if not name.strip() or not objective.strip():
            raise ResearchError("A project needs a name and an objective.")
        root = Path(root or self.home / "projects" / alias).expanduser().resolve()
        # Reserve the registry alias before touching the destination. SQLite serializes creates.
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM projects WHERE alias = ?", (alias,)).fetchone():
                raise ResearchError(f"Project alias already exists: {alias}")
            if root.exists() and (not root.is_dir() or any(root.iterdir())):
                raise ResearchError(f"Project directory must be new or empty: {root}")
            root.mkdir(parents=True, exist_ok=True)
            manifest = {"schema_version": 1, "id": new_id(), "name": name, "created_at": now()}
            atomic_text(root / "brief.md", f"# {name}\n\n{objective.strip()}\n")
            write_json(root / "project.json", manifest)
            self.db.execute("INSERT INTO projects VALUES (?, ?, ?)", (manifest["id"], alias, str(root)))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return self.project(alias)

    def register_project(self, alias: str, root: Path | str) -> dict:
        alias_name(alias)
        root = Path(root).expanduser().resolve()
        manifest = self._manifest(root)
        with self.db:
            existing = self.db.execute("SELECT * FROM projects WHERE id = ?", (manifest["id"],)).fetchone()
            try:
                if existing:
                    self.db.execute("UPDATE projects SET alias = ?, path = ? WHERE id = ?", (alias, str(root), manifest["id"]))
                else:
                    self.db.execute("INSERT INTO projects VALUES (?, ?, ?)", (manifest["id"], alias, str(root)))
            except sqlite3.IntegrityError:
                raise ResearchError("That alias or directory is registered to another project.") from None
        return self.project(alias)

    @staticmethod
    def _manifest(root: Path) -> dict:
        data = read_json(root / "project.json")
        if data.get("schema_version") != 1 or not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ResearchError(f"Unsupported or invalid project manifest: {root}")
        checked_id(data.get("id", ""))
        if not (root / "brief.md").is_file():
            raise ResearchError(f"Missing research brief: {root / 'brief.md'}")
        return data

    def project(self, selector: str) -> dict:
        row = self.db.execute("SELECT * FROM projects WHERE alias = ? OR id = ?", (selector, selector)).fetchone()
        if not row:
            raise ResearchError(f"Unknown project: {selector}. Use 'nullfield project list' or 'nullfield project register'.")
        data = self._manifest(Path(row["path"]))
        if data["id"] != row["id"]:
            raise ResearchError("Project identity changed on disk. Register the correct project directory.")
        return {**data, "alias": row["alias"], "path": row["path"]}

    def list_projects(self) -> list[dict]:
        # Listing remains possible when a registered drive or directory is unavailable.
        return [dict(row) for row in self.db.execute("SELECT * FROM projects ORDER BY alias")]

    def add_resource(self, project: dict, name: str, location: str, kind: str, description: str) -> dict:
        alias_name(name)
        if kind == "reference" and location.startswith(("https://", "http://")):
            resolved = location
        else:
            path = Path(location).expanduser().resolve()
            if not path.exists():
                raise ResearchError(f"Resource does not exist: {path}")
            if kind in ("repo", "directory") and not path.is_dir():
                raise ResearchError(f"Expected a directory: {path}")
            resolved = str(path)
        with self.db:
            self.db.execute("""INSERT INTO resources VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, name) DO UPDATE SET
                kind=excluded.kind, location=excluded.location, description=excluded.description""",
                (project["id"], name, kind, resolved, description))
        return {"project_id": project["id"], "name": name, "kind": kind, "location": resolved, "description": description}

    def resources(self, project: dict) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM resources WHERE project_id = ? ORDER BY name", (project["id"],))]

    def start_session(self, project: dict, agent: str) -> dict:
        session = {"id": new_id(), "project_id": project["id"], "agent": agent, "created_at": now()}
        with self.db:
            self.db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?)", tuple(session.values()))
        return {**session, "project_alias": project["alias"], "project_path": project["path"]}

    def session(self, session_id: str) -> dict:
        try:
            checked_id(session_id)
            rows = self.db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchall()
        except ResearchError:
            if not isinstance(session_id, str) or not ID_PREFIX.fullmatch(session_id):
                raise
            rows = self.db.execute("SELECT * FROM sessions WHERE id LIKE ?", (session_id + "%",)).fetchall()
        if len(rows) > 1:
            raise ResearchError(f"Ambiguous session prefix {session_id}: {', '.join(r['id'] for r in rows[:5])}")
        if not rows:
            raise ResearchError(f"Unknown research session: {session_id}")
        return dict(rows[0])

    def list_sessions(self, project: dict | None = None) -> list[dict]:
        query = "SELECT sessions.*, projects.alias AS project_alias FROM sessions JOIN projects ON project_id = projects.id"
        params = ()
        if project:
            query += " WHERE project_id = ?"
            params = (project["id"],)
        return [dict(r) for r in self.db.execute(query + " ORDER BY created_at DESC", params)]

    def scope(self, project: str | None, session: str | None) -> dict:
        if bool(project) == bool(session):
            raise ResearchError("Specify exactly one of --project or --session.")
        return self.project(project if project else self.session(session)["project_id"])


def record_path(project: dict, collection: str, record_id: str) -> Path:
    return Path(project["path"]) / collection / checked_id(record_id)


ID_PREFIX = re.compile(r"[0-9a-f]{8}[0-9a-f-]{0,28}")


def resolve_id(project: dict, collection: str, value: str) -> str:
    """A full record UUID, or the one record whose UUID starts with a prefix of 8+ hex characters."""
    try:
        return checked_id(value)
    except ResearchError:
        pass
    if not isinstance(value, str) or not ID_PREFIX.fullmatch(value):
        raise ResearchError(f"Invalid ID: {value}. Use a full UUID or a unique prefix of at least 8 characters.")
    matches = sorted(p.parent.name for p in (Path(project["path"]) / collection).glob(f"{value}*/record.json"))
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ResearchError(f"No record in {collection} starts with {value}.")
    raise ResearchError(f"Ambiguous ID prefix {value} in {collection}: {', '.join(matches[:5])}")


def get_record(project: dict, collection: str, record_id: str) -> dict:
    record_id = resolve_id(project, collection, record_id)
    path = record_path(project, collection, record_id)
    record = read_json(path / "record.json")
    if record.get("project_id") != project["id"] or record.get("id") != record_id:
        raise ResearchError(f"Record does not belong to the selected project: {record_id}")
    return {**record, "path": str(path)}


def list_records(project: dict, collection: str) -> list[dict]:
    directory = Path(project["path"]) / collection
    records = [get_record(project, collection, p.parent.name) for p in directory.glob("*/record.json")]
    return sorted(records, key=lambda r: (r["created_at"], r["id"]), reverse=True)


def create_study(project: dict, title: str, plan: str) -> dict:
    if not title.strip() or not plan.strip():
        raise ResearchError("A study needs a title and an experiment plan.")
    record = {"id": new_id(), "project_id": project["id"], "title": title, "created_at": now()}
    path = record_path(project, "studies", record["id"])
    atomic_text(path / "plan.md", plan.strip() + "\n")
    # Metadata is published last so readers do not see half-written records.
    write_json(path / "record.json", record)
    return {**record, "path": str(path)}


def study_freezes(project: dict, study_id: str) -> list[dict]:
    """A study's frozen plan versions, oldest first."""
    directory = record_path(project, "studies", study_id) / "freezes"
    records = [read_json(p) for p in directory.glob("*/record.json")]
    return sorted(records, key=lambda r: (r["created_at"], r["id"]))


def plan_status(project: dict, study: dict) -> str:
    """unfrozen: never frozen; frozen: plan.md matches the latest freeze; drifted: edited since then."""
    freezes = study_freezes(project, study["id"])
    if not freezes:
        return "unfrozen"
    current = hashlib.sha256((Path(study["path"]) / "plan.md").read_bytes()).hexdigest()
    return "frozen" if current == freezes[-1]["plan_sha256"] else "drifted"


def freeze_study(project: dict, study_id: str, note: str) -> dict:
    """Freeze the current plan. Later freezes are amendments and must say why and what had been seen."""
    study = get_record(project, "studies", study_id)
    study_id = study["id"]
    plan = (Path(study["path"]) / "plan.md").read_bytes()
    digest = hashlib.sha256(plan).hexdigest()
    freezes = study_freezes(project, study_id)
    if freezes and freezes[-1]["plan_sha256"] == digest:
        raise ResearchError("The plan is unchanged since its last freeze.")
    if freezes and not note.strip():
        raise ResearchError("An amendment needs --note: what changed, why, and which results were visible.")
    # What this study had already seen when the plan was fixed or changed.
    seen = [u["id"] for u in list_records(project, "uses") if u.get("study_id") == study_id]
    record = {"id": new_id(), "project_id": project["id"], "study_id": study_id,
              "kind": "amendment" if freezes else "freeze", "created_at": now(),
              "plan_sha256": digest, "previous": freezes[-1]["id"] if freezes else None,
              "note": note.strip(), "prior_uses": seen}
    path = Path(study["path"]) / "freezes" / record["id"]
    path.mkdir(parents=True)
    (path / "plan.md").write_bytes(plan)
    write_json(path / "record.json", record)
    return {**record, "path": str(path)}


STUDY_STATES = ("open", "concluded", "abandoned")


def add_entry(project: dict, kind: str, title: str, body: str, study_id: str | None, evidence: list[str],
              supersedes: list[str] = (), study_state: str | None = None) -> dict:
    if not title.strip() or not body.strip():
        raise ResearchError("An entry needs a title and a body.")
    if study_id:
        study_id = get_record(project, "studies", study_id)["id"]
    if study_state is not None:
        if study_state not in STUDY_STATES:
            raise ResearchError(f"Study state must be one of: {', '.join(STUDY_STATES)}")
        if kind != "decision" or not study_id:
            raise ResearchError("Only a decision entry with --study can change a study's state.")
    replaced = []
    for ref in supersedes:
        target = get_record(project, "entries", ref[6:] if ref.startswith("entry:") else ref)["id"]
        if target not in replaced:
            replaced.append(target)
    if kind == "finding" and not evidence:
        raise ResearchError("A finding needs --evidence (a run ID, entry ID, URL, or existing file).")
    resolved = []
    for ref in evidence:
        if ref.startswith("run:"):
            run = get_record(project, "runs", ref[4:])
            if run["status"] == "running":
                raise ResearchError("A running experiment is not completed evidence.")
            resolved.append(f"run:{run['id']}")
        elif ref.startswith("entry:"):
            resolved.append(f"entry:{get_record(project, 'entries', ref[6:])['id']}")
        elif ref.startswith(("https://", "http://")):
            resolved.append(ref)
        else:
            path = Path(ref).expanduser().resolve()
            if not path.is_file():
                raise ResearchError(f"Evidence file does not exist: {path}")
            resolved.append(str(path))
    record = {"id": new_id(), "project_id": project["id"], "kind": kind, "title": title,
              "created_at": now(), "study_id": study_id, "evidence": resolved,
              "supersedes": replaced, "study_state": study_state}
    path = record_path(project, "entries", record["id"])
    atomic_text(path / "note.md", f"# {title}\n\n{body.strip()}\n")
    write_json(path / "record.json", record)
    return {**record, "path": str(path)}


def superseded_by(entries: list[dict]) -> dict[str, list[str]]:
    """Map each superseded entry ID to the IDs of the later entries that replace it."""
    index: dict[str, list[str]] = {}
    for entry in sorted(entries, key=lambda e: (e["created_at"], e["id"])):
        for target in entry.get("supersedes", []):
            index.setdefault(target, []).append(entry["id"])
    return index


def stale_evidence(entry: dict, entries: dict[str, dict], replaced: dict[str, list[str]]) -> list[dict]:
    """Superseded entries this entry's evidence rests on, directly or through the entries it cites.

    A replacement made by the citing entry, or by an entry on the citation path, already accounts
    for the change. The search stops at a superseded entry: its own evidence no longer speaks.
    """
    found, seen = [], {entry["id"]}

    def walk(record: dict, chain: list[str]) -> None:
        for ref in record.get("evidence", []):
            cited = ref[6:] if ref.startswith("entry:") else None
            if cited is None or cited in seen or cited not in entries:
                continue
            seen.add(cited)
            if cited in replaced:
                newer = [r for r in replaced[cited] if r not in chain]
                if newer:
                    found.append({"entry": cited, "superseded_by": newer, "via": chain[1:]})
            else:
                walk(entries[cited], chain + [cited])

    walk(entry, [entry["id"]])
    return found


def study_states(entries: list[dict]) -> dict[str, dict]:
    """Each study's current state: the latest unsuperseded decision that set one. Studies start open.

    A superseded decision no longer speaks for its study, so its replacement must restate the state.
    """
    replaced = superseded_by(entries)
    states: dict[str, dict] = {}
    for entry in sorted(entries, key=lambda e: (e["created_at"], e["id"])):
        if entry.get("study_state") and entry["id"] not in replaced:
            states[entry["study_id"]] = {"state": entry["study_state"], "decision": entry["id"]}
    return states


def annotate(project: dict, collection: str, records: list[dict]) -> list[dict]:
    """Attach derived status: superseded_by and stale_evidence for entries, state for studies."""
    entries = list_records(project, "entries")
    if collection == "entries":
        index, by_id = superseded_by(entries), {e["id"]: e for e in entries}
        return [{**r, "superseded_by": index.get(r["id"], []), "stale_evidence": stale_evidence(r, by_id, index)}
                for r in records]
    if collection == "studies":
        states = study_states(entries)
        return [{**r, **states.get(r["id"], {"state": "open", "decision": None}),
                 "plan_status": plan_status(project, r), "freezes": len(study_freezes(project, r["id"]))}
                for r in records]
    if collection == "runs":
        from .experiments import run_state  # Liveness needs the runner's process helpers.
        return [{**r, "state": run_state(r)} for r in records]
    return records


def search(project: dict, query: str, limit: int = 20) -> list[dict]:
    terms = query.casefold().split()
    if not terms:
        raise ResearchError("Search needs at least one word.")
    matches = []
    for collection, filename in (("entries", "note.md"), ("studies", "plan.md")):
        for record in list_records(project, collection):
            body = (Path(record["path"]) / filename).read_text(encoding="utf-8")
            text = record["title"] + "\n" + body
            if all(term in text.casefold() for term in terms):
                line = next((line for line in body.splitlines() if any(t in line.casefold() for t in terms)), "")
                matches.append({**record, "collection": collection, "excerpt": line[:400]})
    matches = sorted(matches, key=lambda r: r["created_at"], reverse=True)[:limit]
    entries = annotate(project, "entries", [m for m in matches if m["collection"] == "entries"])
    studies = annotate(project, "studies", [m for m in matches if m["collection"] == "studies"])
    annotated = {r["id"]: r for r in entries + studies}
    return [annotated[m["id"]] for m in matches]


def context(store: Store, project: dict, session_id: str | None, limit: int = 10) -> str:
    lines = [f"# Research project: {project['name']}", f"Project ID: {project['id']}",
             f"Alias: {project['alias']}", f"Notebook: {project['path']}",
             f"Research session: {session_id or '(explicit project selection)'}", "",
             "## Brief", (Path(project["path"]) / "brief.md").read_text(encoding="utf-8").strip(),
             "", "## Local resources"]
    for resource in store.resources(project):
        lines.append(f"- {resource['name']} ({resource['kind']}): {resource['location']} — {resource['description']}")
    from .ledger import ledger_lines  # The ledger builds on this module's record helpers.
    lines.extend(["", "## Evaluation samples (all, with recorded use)", *ledger_lines(project)])
    studies = annotate(project, "studies", list_records(project, "studies"))
    entries = annotate(project, "entries", list_records(project, "entries"))
    open_studies = [r for r in studies if r["state"] == "open"]
    questions = [r for r in entries if r["kind"] == "question" and not r["superseded_by"]]
    lines.extend(["", f"## Open studies (all {len(open_studies)})"])
    lines.extend(f"- {r['id']} [plan {r['plan_status']}] {r['title']} — {r['path']}" for r in open_studies)
    lines.extend(["", f"## Open questions (all {len(questions)})"])
    lines.extend(f"- {r['id']} {r['title']} — {r['path']}" for r in questions)
    stale = [r for r in entries if r["stale_evidence"] and not r["superseded_by"]]
    lines.extend(["", f"## Entries citing superseded evidence (all {len(stale)})"])
    for r in stale:
        cited = "; ".join(f"{s['entry']} superseded by {', '.join(s['superseded_by'])}"
                          + (f" (via {', '.join(s['via'])})" if s["via"] else "") for s in r["stale_evidence"])
        lines.append(f"- {r['id']} [{r['kind']}] {r['title']} — cites {cited}")
    runs =annotate(project, "runs", list_records(project, "runs"))
    for collection, records in (("studies", studies), ("entries", entries), ("runs", runs)):
        lines.extend(["", f"## Recent {collection} ({min(limit, len(records))} of {len(records)})"])
        for record in records[:limit]:
            label = record.get("title") or " ".join(record["command"])
            status = record.get("kind") or record.get("state") or record.get("status")
            if record.get("superseded_by"):
                status += f"; superseded by {', '.join(record['superseded_by'])}"
            elif record.get("stale_evidence"):
                status += "; cites superseded evidence"
            lines.append(f"- {record['id']} [{status}] {label} — {record['path']}")
    lines.extend(["", "This is an index, not the complete evidence. Search related studies and entries,",
                  "including negative results, and open the underlying records before continuing."])
    return "\n".join(lines) + "\n"
