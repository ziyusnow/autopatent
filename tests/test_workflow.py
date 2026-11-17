import json
import os
import subprocess
import sys

import pytest
from filelock import FileLock

from autopatent.config import Settings
from autopatent.connectors.models import ModelError
from autopatent.workflow import ResearchApp


def make_app(tmp_path, client):
    return ResearchApp(Settings(data_dir=tmp_path), client, progress=lambda _: None)


def project_id(app):
    return app.store.db.execute("SELECT id FROM projects").fetchone()[0]


def test_completed_project_survives_reopen_and_resume_does_not_call_model(ideas, client_factory, tmp_path):
    client = client_factory(ideas)
    first = make_app(tmp_path, client)
    identifier = first.run(["船舶", "储能"])
    artifact = first.store.get_artifact(identifier)
    first.close()

    second = make_app(tmp_path, client_factory())
    try:
        assert second.status(identifier)["stage"] == "ideation"
        second.resume(identifier)
        assert second.store.get_artifact(identifier) == artifact
        assert second.store.db.execute("SELECT count(*) FROM artifacts").fetchone()[0] == 1
        assert second.store.db.execute("SELECT count(*) FROM model_calls").fetchone()[0] == 1
        assert len(client.messages) == 1
        report = second.store.project_dir(identifier) / "report.md"
        assert "按启动功率排序" in report.read_text(encoding="utf-8")
    finally:
        second.close()


def test_timeout_preserves_failure_and_resume_completes_same_project(ideas, client_factory, tmp_path):
    first = make_app(tmp_path, client_factory(ModelError("模型 API 超时")))
    with pytest.raises(ModelError, match="超时"):
        first.run(["储能"])
    identifier = project_id(first)
    status = first.status(identifier)
    assert status["status"] == "failed"
    assert "超时" in status["error"]
    assert first.store.get_artifact(identifier) is None
    first.close()

    second = make_app(tmp_path, client_factory(ideas))
    try:
        second.resume(identifier)
        assert second.status(identifier)["status"] == "completed"
        assert second.store.db.execute("SELECT count(*) FROM projects").fetchone()[0] == 1
        runs = second.store.db.execute("SELECT status FROM runs ORDER BY rowid").fetchall()
        assert [row[0] for row in runs] == ["failed", "completed"]
    finally:
        second.close()


def test_failure_after_artifact_commit_reuses_output(ideas, client_factory, tmp_path, monkeypatch):
    client = client_factory(ideas)
    first = make_app(tmp_path, client)
    save = first.store.save_artifact

    def save_then_interrupt(*args):
        save(*args)
        raise RuntimeError("checkpoint 尚未写入时退出")

    monkeypatch.setattr(first.store, "save_artifact", save_then_interrupt)
    with pytest.raises(RuntimeError, match="checkpoint"):
        first.run(["船舶"])
    identifier = project_id(first)
    first.close()

    second = make_app(tmp_path, client_factory())
    try:
        second.resume(identifier)
        assert second.status(identifier)["status"] == "completed"
        assert second.store.db.execute("SELECT count(*) FROM model_calls").fetchone()[0] == 1
        assert len(second.store.get_artifact(identifier)["candidates"]) == 4
    finally:
        second.close()


def test_unsupported_stage_and_busy_process_do_not_create_projects(client_factory, tmp_path):
    app = make_app(tmp_path, client_factory())
    try:
        with pytest.raises(ValueError, match="尚未接入"):
            app.run(["船舶"], "design")
        with FileLock(tmp_path / "run.lock"):
            with pytest.raises(ValueError, match="正在运行"):
                app.run(["船舶"])
        assert app.store.db.execute("SELECT count(*) FROM projects").fetchone()[0] == 0
    finally:
        app.close()


def test_status_detects_process_exit_without_marking_a_live_process_interrupted(client_factory, tmp_path):
    app = make_app(tmp_path, client_factory())
    try:
        identifier = app.store.create_project(["储能"])
        app.store.begin_run(identifier)
        with FileLock(tmp_path / "run.lock"):
            assert app.status(identifier)["status"] == "running"
        status = app.status(identifier)
        assert status["status"] == "interrupted"
        assert status["latest_run"]["status"] == "interrupted"
        assert status["latest_run"]["error"] == status["error"]
    finally:
        app.close()


def test_cli_status_and_export_in_new_process_without_model_settings(ideas, client_factory, tmp_path):
    app = make_app(tmp_path / "data", client_factory(ideas))
    identifier = app.run(["船舶", "储能"])
    directory = app.store.project_dir(identifier)
    app.close()
    (directory / "report.md").unlink()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("LLM_", "CODEX_MODEL", "AUTOPATENT_"))}
    env["PYTHONIOENCODING"] = "utf-8"
    command = [sys.executable, "-m", "autopatent", "--data-dir", str(tmp_path / "data"),
               "--env-file", str(tmp_path / "missing.env")]
    status = subprocess.run([*command, "status", identifier], capture_output=True, text=True,
                            encoding="utf-8", env=env, check=True, timeout=30)
    assert json.loads(status.stdout)["status"] == "completed"
    exported = subprocess.run([*command, "export", identifier, "--format", "markdown"],
                              capture_output=True, text=True, encoding="utf-8", env=env,
                              check=True, timeout=30)
    assert str(directory / "report.md") in exported.stdout
    assert "船舶" in (directory / "report.md").read_text(encoding="utf-8")
