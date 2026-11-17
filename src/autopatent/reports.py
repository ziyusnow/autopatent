import json
from pathlib import Path

from autopatent.agents.ideation import IdeationResult
from autopatent.storage import Store


def write_text(path: Path, content: str):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def export_report(store: Store, project_id: str) -> Path:
    project = store.get_project(project_id)
    payload = store.get_artifact(project_id)
    if payload is None:
        raise ValueError("项目尚无 A1 成果，请先 run 或 resume 完成构思。")
    ideas = IdeationResult.model_validate(payload)
    lines = ["# 候选构思报告", "", f"项目：{project_id}", "",
             "关键词：" + "、".join(project["keywords"]), "", "## 研究范围", "",
             ideas.research_scope, "", "术语：" + "；".join(ideas.terminology), ""]
    for index, candidate in enumerate(ideas.candidates, 1):
        lines += [f"## C{index:02d} {candidate.title}", "", "### 技术问题", "", candidate.problem,
                  "", "### 初步机制", "", candidate.mechanism, "", "### 实现条件", ""]
        lines += [f"- {condition}" for condition in candidate.implementation_conditions]
        lines += ["", "### 场景与输出", "", candidate.example_scenario, "", candidate.observable_output,
                  "", "### 后续检索", "", "中文检索词：" + "；".join(candidate.search_terms_zh), "",
                  "英文检索词：" + "; ".join(candidate.search_terms_en), "", candidate.search_hypothesis, ""]
    lines += ["## 当前进度", "", "已完成 A1 关键词构思。下一阶段为真实检索与候选对比。", ""]
    directory = store.project_dir(project_id)
    directory.mkdir(parents=True, exist_ok=True)
    write_text(directory / "ideation.json", json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    target = directory / "report.md"
    write_text(target, "\n".join(lines))
    return target
