from contextlib import contextmanager
from typing import Callable, TypedDict

from filelock import FileLock, Timeout
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph

from autopatent.agents.ideation import IdeationInput, generate_ideas
from autopatent.config import Settings
from autopatent.connectors.models import ModelClient, create_client
from autopatent.reports import export_report
from autopatent.storage import Store

STAGES = ("ideation", "search", "design", "draft", "word")


def check_stage(until: str):
    if until != "ideation":
        raise ValueError(f"阶段 {until} 尚未接入；当前 M1 支持 --until ideation。")


class ResearchState(TypedDict):
    project_id: str
    stage: str


class ResearchApp:
    def __init__(self, settings: Settings, client: ModelClient | None = None,
                 progress: Callable[[str], None] = print):
        self.settings = settings
        self.store = Store(settings.data_dir)
        self.client = client
        self.progress = progress

    def close(self):
        self.store.close()

    @contextmanager
    def execution_lock(self):
        lock = FileLock(self.store.root / "run.lock")
        try:
            lock.acquire(timeout=0)
        except Timeout as exc:
            raise ValueError("已有研究项目正在运行，请等待完成后再启动或恢复。") from exc
        try:
            yield
        finally:
            lock.release()

    def run(self, keywords: list[str], until: str = "ideation") -> str:
        check_stage(until)
        inputs = IdeationInput(keywords=keywords)
        with self.execution_lock():
            project_id = self.store.create_project(inputs.keywords)
            self.progress(f"项目已创建：{project_id}")
            self._execute(project_id)
        return project_id

    def resume(self, project_id: str, until: str = "ideation") -> str:
        check_stage(until)
        self.store.get_project(project_id)
        with self.execution_lock():
            self._execute(project_id)
        return project_id

    def _execute(self, project_id: str):
        run_id = self.store.begin_run(project_id)
        try:
            def ideation(state: ResearchState):
                if self.store.get_artifact(project_id) is not None:
                    self.progress("A1 已保存，复用现有候选。")
                else:
                    self.progress("当前节点：A1 关键词理解与候选构思")
                    inputs = IdeationInput(keywords=self.store.get_project(project_id)["keywords"])
                    client = self.client or create_client(self.settings)
                    result = generate_ideas(
                        inputs, client, self.store.project_dir(project_id) / "runs" / run_id,
                        lambda attempt, response, issues: self.store.record_call(run_id, attempt, response, issues),
                        self.progress,
                    )
                    self.store.save_artifact(project_id, run_id, result.model_dump())
                return {"stage": "ideation"}

            graph = StateGraph(ResearchState)
            graph.add_node("ideation", ideation)
            graph.add_edge(START, "ideation")
            graph.add_edge("ideation", END)
            with SqliteSaver.from_conn_string(str(self.store.root / "checkpoints.sqlite3")) as saver:
                workflow = graph.compile(checkpointer=saver)
                config = {"configurable": {"thread_id": project_id}}
                snapshot = workflow.get_state(config)
                if snapshot.next:
                    self.progress("从已保存检查点继续。")
                    workflow.invoke(None, config)
                elif not snapshot.values:
                    workflow.invoke({"project_id": project_id, "stage": ""}, config)
                else:
                    self.progress("A1 已完成，复用现有候选。")
            report = export_report(self.store, project_id)
            self.store.finish_run(project_id, run_id, "completed")
            self.progress(f"已完成 ideation；报告：{report}")
        except KeyboardInterrupt:
            self.store.finish_run(project_id, run_id, "interrupted", "用户中断；可用 resume 继续。")
            raise
        except Exception as exc:
            self.store.finish_run(project_id, run_id, "failed", str(exc))
            raise

    def status(self, project_id: str) -> dict:
        project = self.store.get_project(project_id)
        project["latest_run"] = self.store.latest_run(project_id)
        project["next_stage"] = "search" if project["stage"] == "ideation" else "ideation"
        if project["status"] == "running":
            lock = FileLock(self.store.root / "run.lock")
            try:
                with lock.acquire(timeout=0):
                    project["status"] = "interrupted"
                    project["error"] = "执行进程已退出；可用 resume 继续。"
                    if project["latest_run"] and project["latest_run"]["status"] == "running":
                        project["latest_run"]["status"] = "interrupted"
                        project["latest_run"]["error"] = project["error"]
            except Timeout:
                pass
        return project
