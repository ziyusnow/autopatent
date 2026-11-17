import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "state.sqlite3")
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, keywords TEXT NOT NULL, status TEXT NOT NULL,
                stage TEXT, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                status TEXT NOT NULL, error TEXT, started_at TEXT NOT NULL, finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS artifacts (
                project_id TEXT NOT NULL REFERENCES projects(id), node TEXT NOT NULL,
                run_id TEXT NOT NULL REFERENCES runs(id), payload TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(project_id, node)
            );
            CREATE TABLE IF NOT EXISTS model_calls (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                node TEXT NOT NULL, attempt INTEGER NOT NULL, model TEXT NOT NULL,
                response TEXT NOT NULL, usage TEXT NOT NULL, issues TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

    def close(self):
        self.db.close()

    def create_project(self, keywords: list[str]) -> str:
        project_id = uuid4().hex
        with self.db:
            self.db.execute("INSERT INTO projects VALUES (?, ?, 'created', NULL, NULL, ?, ?)",
                            (project_id, json.dumps(keywords, ensure_ascii=False), now(), now()))
        self.project_dir(project_id).mkdir(parents=True, exist_ok=True)
        return project_id

    def get_project(self, project_id: str) -> dict:
        row = self.db.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if row is None:
            raise ValueError(f"项目不存在：{project_id}")
        result = dict(row)
        result["keywords"] = json.loads(result["keywords"])
        return result

    def project_dir(self, project_id: str) -> Path:
        self.get_project(project_id)
        return self.root / "projects" / project_id

    def get_artifact(self, project_id: str, node: str = "ideation") -> dict | None:
        row = self.db.execute("SELECT payload FROM artifacts WHERE project_id=? AND node=?",
                              (project_id, node)).fetchone()
        return json.loads(row[0]) if row else None

    def begin_run(self, project_id: str) -> str:
        run_id = uuid4().hex
        with self.db:
            # 调用方已获得单实例锁，此时残留 running 记录来自中断的进程。
            self.db.execute("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (now(),))
            self.db.execute("UPDATE projects SET status='interrupted', updated_at=? WHERE status='running'", (now(),))
            self.db.execute("INSERT INTO runs VALUES (?, ?, 'running', NULL, ?, NULL)",
                            (run_id, project_id, now()))
            self.db.execute("UPDATE projects SET status='running', error=NULL, updated_at=? WHERE id=?",
                            (now(), project_id))
        return run_id

    def save_artifact(self, project_id: str, run_id: str, payload: dict):
        with self.db:
            self.db.execute("INSERT INTO artifacts VALUES (?, 'ideation', ?, ?, ?) "
                            "ON CONFLICT(project_id, node) DO NOTHING",
                            (project_id, run_id, json.dumps(payload, ensure_ascii=False), now()))
            self.db.execute("UPDATE projects SET stage='ideation', updated_at=? WHERE id=?", (now(), project_id))

    def record_call(self, run_id: str, attempt: int, response, issues: list):
        with self.db:
            self.db.execute("INSERT INTO model_calls (run_id, node, attempt, model, response, usage, issues, created_at) "
                            "VALUES (?, 'ideation', ?, ?, ?, ?, ?, ?)",
                            (run_id, attempt, response.model, response.text,
                             json.dumps(response.usage), json.dumps(issues, ensure_ascii=False), now()))

    def finish_run(self, project_id: str, run_id: str, status: str, error: str | None = None):
        with self.db:
            self.db.execute("UPDATE runs SET status=?, error=?, finished_at=? WHERE id=?", (status, error, now(), run_id))
            self.db.execute("UPDATE projects SET status=?, error=?, updated_at=? WHERE id=?", (status, error, now(), project_id))

    def latest_run(self, project_id: str) -> dict | None:
        row = self.db.execute("SELECT * FROM runs WHERE project_id=? ORDER BY rowid DESC LIMIT 1", (project_id,)).fetchone()
        return dict(row) if row else None
