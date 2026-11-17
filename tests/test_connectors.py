import json
import os
import sys

import httpx
import pytest

from autopatent.config import Settings
from autopatent.connectors import models
from autopatent.connectors.models import APIClient, CodexClient, ModelError


def api_settings():
    return Settings(provider="api", llm_base_url="https://model.invalid/v1/",
                    llm_api_key="secret-test-key", llm_model="test-model")


def install_transport(monkeypatch, handler):
    original = httpx.Client
    monkeypatch.setattr(models.httpx, "Client", lambda **kwargs: original(
        transport=httpx.MockTransport(handler), **kwargs))


def test_api_sends_configured_request_and_parses_usage(monkeypatch, tmp_path):
    def handler(request):
        assert str(request.url) == "https://model.invalid/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret-test-key"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["messages"][0]["content"] == "生成候选"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}],
                                         "usage": {"completion_tokens": 10}, "model": "actual-model"})

    install_transport(monkeypatch, handler)
    result = APIClient(api_settings()).generate([{"role": "user", "content": "生成候选"}], {}, tmp_path)
    assert result.text == '{"ok":true}'
    assert result.usage == {"completion_tokens": 10}
    assert result.model == "actual-model"


@pytest.mark.parametrize("failure", ["timeout", "401", "malformed"])
def test_api_failures_are_actionable_without_echoing_secret(monkeypatch, tmp_path, failure):
    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret-test-key", request=request)
        if failure == "401":
            return httpx.Response(401, text="secret-test-key")
        return httpx.Response(200, json={"choices": [], "error": "secret-test-key"})

    install_transport(monkeypatch, handler)
    with pytest.raises(ModelError) as error:
        APIClient(api_settings()).generate([], {}, tmp_path)
    assert "secret-test-key" not in str(error.value)


def test_codex_reads_final_file_and_jsonl_usage_without_shell(monkeypatch, tmp_path):
    script = tmp_path / "fake_codex.py"
    script.write_text('''import json, os, pathlib, sys
args = sys.argv[1:]
assert not any(key in os.environ for key in ("CODEX_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"))
assert os.environ["AUTOPATENT_TEST_MARKER"] == "preserved"
schema = pathlib.Path(args[args.index("--output-schema") + 1])
assert json.loads(schema.read_text(encoding="utf-8"))["type"] == "object"
assert "只根据" in sys.stdin.read()
output = pathlib.Path(args[args.index("--output-last-message") + 1])
output.write_text('{"ok":true}', encoding="utf-8")
print(json.dumps({"type":"turn.completed", "usage":{"output_tokens":5}}))
''', encoding="utf-8")
    monkeypatch.setattr(models, "_codex_command", lambda _: [sys.executable, str(script)])
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")
    for name in ("CODEX_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"):
        monkeypatch.setenv(name, "test-host-key")
    monkeypatch.setenv("AUTOPATENT_TEST_MARKER", "preserved")
    result = CodexClient(Settings()).generate([{"role": "user", "content": "测试"}], {"type": "object"}, tmp_path)
    assert result.text == '{"ok":true}'
    assert result.usage == {"output_tokens": 5}
    assert os.environ["CODEX_API_KEY"] == "test-host-key"


def test_codex_timeout_terminates_process(monkeypatch, tmp_path):
    script = tmp_path / "fake_codex.py"
    script.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    monkeypatch.setattr(models, "_codex_command", lambda _: [sys.executable, str(script)])
    processes = []
    original = models.subprocess.Popen

    def popen(*args, **kwargs):
        process = original(*args, **kwargs)
        if "stdin" in kwargs:
            processes.append(process)
        return process

    monkeypatch.setattr(models.subprocess, "Popen", popen)
    with pytest.raises(ModelError, match="超过"):
        CodexClient(Settings(timeout_seconds=0.2)).generate([], {}, tmp_path)
    assert len(processes) == 1
    assert processes[0].poll() is not None
