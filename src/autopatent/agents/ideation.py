import json
from pathlib import Path
from typing import Annotated, Callable

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from autopatent.connectors.models import ModelClient, ModelError

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TextList = Annotated[list[Text], Field(min_length=1)]


class AgentData(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdeationInput(AgentData):
    keywords: TextList


class Candidate(AgentData):
    title: Text
    problem: Text
    mechanism: Text
    implementation_conditions: TextList
    example_scenario: Text
    observable_output: Text
    search_terms_zh: TextList
    search_terms_en: TextList
    search_hypothesis: Text


class IdeationResult(AgentData):
    research_scope: Text
    terminology: TextList
    candidates: list[Candidate] = Field(min_length=4, max_length=5)

    @model_validator(mode="after")
    def distinct_titles(self) -> "IdeationResult":
        titles = [item.title.casefold() for item in self.candidates]
        if len(set(titles)) != len(titles):
            raise ValueError("候选标题必须不同")
        return self


SYSTEM_PROMPT = """你是自动化科研工作流的 A1 关键词理解与选题构思 Agent。
用户只提供几个关键词。请自主明确研究场景、技术问题和候选机制，生成 4–5 个实质不同的候选。
围绕可实现的结构、步骤或控制关系展开，而非仅替换算法名称或堆叠热点术语。
每个候选写清：标题、问题、机制、数据/设备/软件条件、一个具体应用场景、可观察输出、
中英文检索词，以及后续应检索确认的技术假设。优先考虑个人小规模研究能够实现的方向。
本阶段是构思，文献检索由后续节点执行：不编造论文、公开号、已验证的新颖性或性能数据。
不需要用户先给创新点或技术路线，也不需要提问。仅依据本次输入直接返回 JSON。
不要执行命令、访问文件、联网检索或调用其他工具；所有必需输入均在消息中。
除英文检索词外使用中文。输出遵循提供的 JSON Schema。
"""


def generate_ideas(inputs: IdeationInput, client: ModelClient, workdir: Path,
                   record_call: Callable, progress: Callable[[str], None]) -> IdeationResult:
    schema = IdeationResult.model_json_schema()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(inputs.model_dump(), ensure_ascii=False)
         + "\nJSON Schema:\n" + json.dumps(schema, ensure_ascii=False)},
    ]
    for attempt in range(1, 3):
        progress(f"A1 模型调用 {attempt}/2" + ("（修复输出格式）" if attempt == 2 else ""))
        response = client.generate(messages, schema, workdir)
        try:
            result = IdeationResult.model_validate_json(response.text)
        except ValidationError as exc:
            issues = [{"location": list(e["loc"]), "reason": e["msg"]}
                      for e in exc.errors(include_input=False, include_url=False)]
            record_call(attempt, response, issues)
            if attempt == 2:
                details = "; ".join(
                    f"{'.'.join(map(str, issue['location'])) or '根对象'}: {issue['reason']}"
                    for issue in issues
                )
                raise ModelError(f"A1 输出格式修复一次后仍不符合要求：{details}；可 resume 重试。") from exc
            messages.extend([
                {"role": "assistant", "content": response.text},
                {"role": "user", "content": "请修复以下结构问题，保留完整内容并重新输出 JSON："
                 + json.dumps(issues, ensure_ascii=False)},
            ])
        else:
            record_call(attempt, response, [])
            return result
    raise AssertionError("unreachable")
