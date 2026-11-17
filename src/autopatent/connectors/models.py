"""Small synchronous model adapters used by the workflow."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

import httpx

if TYPE_CHECKING:
    from autopatent.config import Settings


class ModelError(RuntimeError):
    """An actionable model transport error, without credentials or response bodies."""


@dataclass
class ModelResponse:
    text: str
    usage: dict
    model: str


class ModelClient(Protocol):
    def generate(
        self, messages: list[dict[str, str]], schema: dict, workdir: Path
    ) -> ModelResponse: ...


def _codex_command(command: str) -> list[str]:
    executable = shutil.which(command)
    if not executable:
        raise ModelError("未找到 Codex CLI；请安装 Codex 并执行 codex login。")
    path = Path(executable)
    if os.name == "nt" and path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        # Run npm's JavaScript entry point directly, without cmd.exe or shell quoting.
        entry = path.parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        local_node = path.parent / "node.exe"
        node = str(local_node) if local_node.is_file() else shutil.which("node")
        if not entry.is_file() or not node:
            raise ModelError("无法定位 Codex 的 npm 入口；请将 CODEX_COMMAND 指向 codex.exe。")
        return [node, str(entry)]
    return [str(path)]


def _stop_process(process: subprocess.Popen) -> None:
    """Terminate the CLI and its native child, including on Ctrl+C."""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.communicate()


def _codex_failure(output: str, returncode: int) -> ModelError:
    # Do not echo raw CLI errors: providers may include credentials or request data.
    lowered = output.lower()
    if any(word in lowered for word in ("unauthorized", "401", "not logged in", "refresh token")):
        reason = "认证被拒绝，请用 codex login status 检查登录与模型访问权限后 resume"
    elif any(word in lowered for word in ("429", "usage limit", "rate limit", "quota")):
        reason = "账号额度或速率限制，请恢复可用额度后 resume"
    elif any(word in lowered for word in ("connect", "network", "timed out", "stream disconnected")):
        reason = "网络连接失败，请检查网络或代理后 resume"
    elif any(word in lowered for word in ("access is denied", "permission denied", "os error 5")):
        reason = "本机文件或进程权限不足，请在可访问 Codex 用户目录的终端运行"
    else:
        reason = "请用 codex login status 检查登录，并确认 CLI 支持 exec --output-schema"
    return ModelError(f"Codex 调用失败（退出码 {returncode}）：{reason}。")


class CodexClient:
    def __init__(self, settings: Settings):
        self.command = _codex_command(settings.codex_command)
        self.model = settings.codex_model
        self.timeout = settings.timeout_seconds

    def generate(
        self, messages: list[dict[str, str]], schema: dict, workdir: Path
    ) -> ModelResponse:
        call_dir = (workdir / "calls" / uuid4().hex).resolve()
        call_dir.mkdir(parents=True)
        schema_path = call_dir / "schema.json"
        result_path = call_dir / "response.json"
        schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
        command = [
            *self.command,
            "exec", "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "--color", "never", "--json",
            "-c", "features.shell_tool=false", "-c", "web_search=\"disabled\"",
            "-c", "agents.enabled=false", "-c", "project_doc_max_bytes=0",
            "--output-schema", str(schema_path),
            "--output-last-message", str(result_path),
            "--cd", str(call_dir),
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.append("-")
        prompt = "只根据以下任务生成最终 JSON，不调用工具、不读取文件、不执行命令。\n\n"
        prompt += "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)
        options: dict = {"start_new_session": True} if os.name != "nt" else {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        }
        try:
            # This provider deliberately uses saved CLI auth; an API key inherited
            # from a host application must not silently replace that login.
            environment = {key: value for key, value in os.environ.items()
                           if key.upper() not in {"CODEX_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"}}
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", cwd=call_dir,
                env=environment, **options,
            )
        except OSError as exc:
            raise ModelError(f"无法启动 Codex CLI（{type(exc).__name__}）。") from exc
        try:
            stdout, stderr = process.communicate(prompt, timeout=self.timeout)
        except subprocess.TimeoutExpired as exc:
            _stop_process(process)
            raise ModelError(f"Codex 调用超过 {self.timeout:g} 秒；可执行 resume 重试。") from exc
        except KeyboardInterrupt:
            _stop_process(process)
            raise
        if process.returncode:
            raise _codex_failure(stderr + "\n" + stdout, process.returncode)
        if not result_path.is_file():
            raise ModelError("Codex 未生成最终响应；可执行 resume 重试。")
        usage = {}
        for line in stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "turn.completed":
                usage = event.get("usage") or {}
        return ModelResponse(
            text=result_path.read_text(encoding="utf-8"),
            usage=usage,
            model=self.model or "codex-default",
        )


class APIClient:
    def __init__(self, settings: Settings):
        missing = [name for name in ("llm_base_url", "llm_api_key", "llm_model")
                   if not getattr(settings, name)]
        if missing:
            raise ModelError("API 配置缺少：" + "、".join(name.upper() for name in missing))
        self.url = settings.llm_base_url.rstrip("/") + "/chat/completions"
        self.key = settings.llm_api_key
        self.model = settings.llm_model
        self.timeout = settings.timeout_seconds

    def generate(
        self, messages: list[dict[str, str]], schema: dict, workdir: Path
    ) -> ModelResponse:
        request_messages = [*messages, {
            "role": "user",
            "content": "只返回符合以下 JSON Schema 的 JSON 对象：\n" + json.dumps(schema, ensure_ascii=False),
        }]
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(
                    self.url,
                    headers={"Authorization": f"Bearer {self.key}"},
                    json={"model": self.model, "messages": request_messages},
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ModelError(f"模型 API 超过 {self.timeout:g} 秒未完成；可执行 resume 重试。") from exc
        except httpx.HTTPStatusError as exc:
            raise ModelError(f"模型 API 返回 HTTP {exc.response.status_code}；请检查配置、额度或服务状态。") from exc
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise ModelError("模型 API 连接失败；请检查接口地址、网络或代理。") from exc
        try:
            payload = response.json()
            content = payload["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("content is not text")
            return ModelResponse(content, payload.get("usage") or {}, payload.get("model") or self.model)
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ModelError("模型 API 响应缺少 choices[0].message.content 文本。") from exc


def create_client(settings: Settings) -> ModelClient:
    if settings.provider == "codex":
        return CodexClient(settings)
    if settings.provider == "api":
        return APIClient(settings)
    raise ModelError(f"不支持模型后端：{settings.provider}。")
