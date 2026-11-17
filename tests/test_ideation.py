import copy

import pytest
from pydantic import ValidationError

from autopatent.agents.ideation import IdeationInput, IdeationResult, generate_ideas
from autopatent.connectors.models import ModelError


@pytest.mark.parametrize("count", [3, 6])
def test_candidate_count_outside_four_to_five_is_rejected(ideas, count):
    while len(ideas["candidates"]) < count:
        candidate = copy.deepcopy(ideas["candidates"][0])
        candidate["title"] = str(len(ideas["candidates"]))
        ideas["candidates"].append(candidate)
    ideas["candidates"] = ideas["candidates"][:count]
    with pytest.raises(ValidationError):
        IdeationResult.model_validate(ideas)


def test_blank_conditions_and_repeated_titles_are_rejected(ideas):
    ideas["candidates"][0]["implementation_conditions"] = ["   "]
    with pytest.raises(ValidationError):
        IdeationResult.model_validate(ideas)
    ideas["candidates"][0]["implementation_conditions"] = ["设备记录"]
    ideas["candidates"][1]["title"] = ideas["candidates"][0]["title"]
    with pytest.raises(ValidationError, match="候选标题"):
        IdeationResult.model_validate(ideas)


def test_one_format_repair_retains_error_and_original_response(ideas, client_factory, tmp_path):
    client = client_factory("not JSON", ideas)
    records = []
    result = generate_ideas(IdeationInput(keywords=["船舶"]), client, tmp_path,
                            lambda *record: records.append(record), lambda _: None)
    assert len(result.candidates) == 4
    assert [record[0] for record in records] == [1, 2]
    assert records[0][2] and not records[1][2]
    assert client.messages[1][-2] == {"role": "assistant", "content": "not JSON"}


def test_second_invalid_response_stops_repair(client_factory, tmp_path):
    client = client_factory("bad", "bad again", "must not be called")
    records = []
    with pytest.raises(ModelError, match="修复一次"):
        generate_ideas(IdeationInput(keywords=["储能"]), client, tmp_path,
                       lambda *record: records.append(record), lambda _: None)
    assert len(client.messages) == 2
    assert len(records) == 2
