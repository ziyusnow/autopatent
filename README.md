# AutoPatent

从几个关键词启动科研与专利工作流。当前首批 M1 实现命令行、A1 候选构思、SQLite 保存、LangGraph 检查点和 Markdown 导出。

A1 自主生成 4–5 个候选，包含技术问题、初步机制、实现条件、具体场景、可观察输出和中英文检索词。真实检索、全文分析、方案选择及 Word 交付按 M2–M6 继续接入，详见 [实施规划](IMPLEMENTATION_PLAN.md)。

## 安装与运行

需要 Python 3.12 或更高版本。在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

默认通过本机 `codex exec` 调用模型，复用已有 Codex CLI 登录。先确认 `codex` 在 PATH 中：

```powershell
codex --version
codex login status
# 尚未登录时执行：codex login

.\.venv\Scripts\autopatent.exe run --keywords "船舶、储能、故障恢复" --until ideation
```

这种调用不需要填写 API 密钥，也不需要创建 `.env`。它使用 Codex CLI 的非交互接口和结构化输出；当前没有接入 ACP。登录复用方式见 [Codex 官方说明](https://learn.chatgpt.com/docs/non-interactive-mode)。

终端会显示项目 ID、当前节点和报告路径。以下示例中的 `<project_id>` 替换为实际项目 ID：

```text
autopatent status <project_id>
autopatent resume <project_id> --until ideation
autopatent export <project_id> --format markdown
```

激活虚拟环境后可直接使用 `autopatent`；未激活时使用 `.\.venv\Scripts\autopatent.exe`，也可执行 `.\.venv\Scripts\python.exe -m autopatent`。

当前仅支持执行到 `ideation`。`search`、`design`、`draft`、`word` 随后续批次接通，提前指定会提示尚未实现。

## 配置

需要调整模型、超时或存储位置时，将 `.env.example` 复制为 `.env`。默认配置为：

```dotenv
LLM_PROVIDER=codex
CODEX_COMMAND=codex
CODEX_MODEL=
LLM_TIMEOUT_SECONDS=300
AUTOPATENT_DATA_DIR=data
```

`CODEX_MODEL` 留空时使用 Codex 默认模型，也可填写当前账号可用的模型名。该适配器只承担当前节点的内容生成，不加载用户 Codex 配置中的额外 MCP 服务。Codex 子进程不继承宿主的 API Key 变量，以免覆盖已保存的 ChatGPT 登录；宿主环境不变。

使用兼容 Chat Completions 的 API 时，改为：

```dotenv
LLM_PROVIDER=api
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=你的密钥
LLM_MODEL=你的模型名
```

程序在 `LLM_BASE_URL` 后追加 `/chat/completions`；地址需包含服务要求的版本前缀。环境变量优先于 `.env`，密钥和运行数据已加入 Git 忽略规则。

自定义配置文件和数据目录的参数放在子命令前：

```text
autopatent --env-file local.env --data-dir research-data run --keywords "船舶、储能" --until ideation
```

默认读取当前工作目录下的 `.env`，相对数据路径也以当前工作目录为基准。后续 `status`、`resume`、`export` 使用同一数据目录。

## 保存与恢复

```text
data/
  state.sqlite3                 项目、运行、节点成果和模型调用记录
  checkpoints.sqlite3           LangGraph 执行检查点
  projects/<project_id>/
    ideation.json               结构化候选
    report.md                   可阅读的构思报告
    runs/<run_id>/calls/...     Codex 调用的输出结构与响应文件
```

同一数据目录一次运行一个研究项目。节点成果与检查点分别保存；恢复时复用已完成的候选，不重复追加。`export` 从数据库重新生成当前报告。

模型输出格式错误时自动修复一次。超时、认证或服务错误会保存失败状态和原因，处理后执行 `resume`；关闭程序后仍可查询成果。`status` 和 `export` 不调用模型。

## 模块与后续工作

| 模块 | 当前职责 |
|---|---|
| `workflow.py` | 应用入口、LangGraph 节点、执行与恢复 |
| `agents/ideation.py` | A1 提示词、Pydantic 类型、格式修复 |
| `connectors/models.py` | Codex CLI 与兼容 API 调用 |
| `storage.py` | SQLite 状态、节点成果和调用记录 |
| `reports.py` | JSON 与 Markdown 导出 |
| `cli.py` | 命令行参数与终端进度 |

后续按真实检索 → 全文与方案 → 专利内容 → 审阅与 Word → 返稿处理推进。服务模块、MCP 连接器和 OfficeCLI 文档模块在对应批次加入；浏览器页面与 FastAPI 接口在核心流程稳定后接入同一应用入口。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest
```

自动测试覆盖结构校验、格式修复、保存与恢复等行为。真实模型验收另行执行 `run`，检查候选内容，再通过新进程执行 `status`、`resume` 和 `export` 验证落盘与复用。

2026-11-16 本机验收：17 项自动测试通过；通过已登录的 Codex 实际运行“船舶、储能、故障恢复”，生成 5 个候选并保存 JSON 和 Markdown。新进程查询、续跑、导出通过，续跑后模型调用记录仍为 1 条。样例位于 `data/projects/04738c217ab04a28898e9ea4218c4bda/`（本地运行数据，不纳入 Git）。
