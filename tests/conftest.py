import copy
import json

import pytest

from autopatent.connectors.models import ModelResponse


@pytest.fixture
def ideas():
    return {
        "research_scope": "船舶储能故障恢复",
        "terminology": ["储能", "负荷恢复"],
        "candidates": [
            {
                "title": title,
                "problem": "恢复期间储能功率不足，部分关键负荷无法接入。",
                "mechanism": "根据可用储能功率和负荷启动需求安排接入顺序。",
                "implementation_conditions": ["负荷功率记录", "储能状态估计"],
                "example_scenario": "一台发电机退出后重新接入辅助负荷。",
                "observable_output": "接入顺序及各时段电池功率。",
                "search_terms_zh": ["船舶故障恢复"],
                "search_terms_en": ["ship fault restoration"],
                "search_hypothesis": "检索已有接入顺序与储能约束联合控制方法。",
            }
            for title in ("按启动功率排序", "按剩余能量分组", "按故障区域隔离", "按恢复窗口分配")
        ],
    }


class SequenceClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.messages = []

    def generate(self, messages, schema, workdir):
        self.messages.append(copy.deepcopy(messages))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if not isinstance(response, str):
            response = json.dumps(response, ensure_ascii=False)
        return ModelResponse(response, {"output_tokens": 100}, "test-model")


@pytest.fixture
def client_factory():
    return SequenceClient
