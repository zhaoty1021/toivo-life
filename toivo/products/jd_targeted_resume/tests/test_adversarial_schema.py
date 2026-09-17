"""
Phase 1 · Schema 硬红线的 6 组 adversarial 用例。

每组用例都是"看似合理但破坏契约"的 LLM 输出。它们**必须**在 schema 层被拒收 —— 如果
某天有一个 case 不再抛错, 说明 schema 的护栏被削弱了, 需要立即修复。

用例来源: fixture_smoke_v1.json (已知能通过) 上做**单点变异**, 每次只破坏一个契约,
以确保测出来的失败信号来自那条契约本身, 而不是无关的兜底校验。

契约 → 用例映射
  1. 三段分层只允许对应 requirement_type   → test_preferred_in_blockers
  2. jd_requirements[].id 全局唯一          → test_dup_id
  3. match_board 与 jd_requirements 全量覆盖 → test_board_missing_row
  4. must_have_blockers 必须闭环到 rewrite_card → test_blocker_no_link
  5. blocker→rewrite→target 三向闭环         → test_rewrite_no_target
  6. inferred requirement 描述禁止数字/年限   → test_inferred_with_number
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from toivo.products.jd_targeted_resume.schema import JDTargetedResumeReport


FIXTURE_PATH = Path(__file__).parent / "fixture_smoke_v1.json"


@pytest.fixture
def valid_payload() -> dict:
    """基准 payload —— 每个 adversarial 用例都在这份深拷贝上做单点变异。"""
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _validation_message(exc: pytest.ExceptionInfo[ValidationError]) -> str:
    """拉平 Pydantic ValidationError 的所有 msg, 便于用 substring 匹配。"""
    return " || ".join(err["msg"] for err in exc.value.errors())


def test_smoke_baseline_passes(valid_payload):
    """基准 fixture 必须通过 —— 否则 adversarial 用例的"变异"参照系失效。"""
    JDTargetedResumeReport.model_validate(valid_payload)


def test_preferred_in_blockers(valid_payload):
    """把 preferred 类要求 (REQ-03) 塞进 must_have_blockers → 必须拒收。"""
    valid_payload["must_have_blockers"].append({
        "jd_requirement_id": "REQ-03",  # requirement_type == preferred
        "problem": "P0 稳定性经历未呈现",
        "severity": "high",
        "impact_stage": "screening",
        "impact_explanation": "面试官会因此跳过",
        "recommended_action": "补一条稳定性 bullet",
        "linked_rewrite_card_id": "RW-02",
    })
    with pytest.raises(ValidationError) as exc:
        JDTargetedResumeReport.model_validate(valid_payload)
    msg = _validation_message(exc)
    assert "只允许指向 requirement_type=must_have" in msg


def test_dup_id(valid_payload):
    """两条 jd_requirements 共用 REQ-01 → 必须拒收。"""
    dup = copy.deepcopy(valid_payload["jd_requirements"][0])
    dup["requirement"] = "另一条要求, 但故意用了同一个 id"
    valid_payload["jd_requirements"].append(dup)
    with pytest.raises(ValidationError) as exc:
        JDTargetedResumeReport.model_validate(valid_payload)
    msg = _validation_message(exc)
    assert "出现重复 id" in msg
    assert "jd_requirements" in msg


def test_board_missing_row(valid_payload):
    """从 match_board.items 里删掉 REQ-06 那一行 → 必须拒收 (全量覆盖破裂)。"""
    valid_payload["match_board"]["items"] = [
        item for item in valid_payload["match_board"]["items"]
        if item["jd_requirement_id"] != "REQ-06"
    ]
    with pytest.raises(ValidationError) as exc:
        JDTargetedResumeReport.model_validate(valid_payload)
    msg = _validation_message(exc)
    assert "没有对应行" in msg
    assert "REQ-06" in msg


def test_blocker_no_link(valid_payload):
    """把 must_have_blockers[0].linked_rewrite_card_id 清空 → 必须拒收 (硬红线)。"""
    valid_payload["must_have_blockers"][0]["linked_rewrite_card_id"] = ""
    with pytest.raises(ValidationError) as exc:
        JDTargetedResumeReport.model_validate(valid_payload)
    msg = _validation_message(exc)
    # min_length=1 校验在 Pydantic v2 里报错含 "at least 1 character"
    assert re.search(r"at least 1 character|min_length", msg, re.IGNORECASE)


def test_rewrite_no_target(valid_payload):
    """RW-01 的 targets_requirement_ids 里把 REQ-01 去掉 → blocker 关联的改写卡不再瞄准该 blocker → 必须拒收。"""
    for card in valid_payload["rewrite_cards"]:
        if card["id"] == "RW-01":
            card["targets_requirement_ids"] = [
                rid for rid in card["targets_requirement_ids"] if rid != "REQ-01"
            ]
            # 保证 targets 非空, 否则会先撞到"每张卡至少凸显一条 requirement"那道校验
            if not card["targets_requirement_ids"]:
                card["targets_requirement_ids"] = ["REQ-05"]
    with pytest.raises(ValidationError) as exc:
        JDTargetedResumeReport.model_validate(valid_payload)
    msg = _validation_message(exc)
    assert "闭环断裂" in msg


def test_inferred_with_number(valid_payload):
    """把 REQ-05 (inferred_from_context) 的描述改成含"5 年"数字 → 必须拒收。"""
    for req in valid_payload["jd_requirements"]:
        if req["id"] == "REQ-05":
            req["requirement"] = "具备 5 年以上高并发场景架构演进经验"
    # match_board 里的冗余拷贝也要同步, 否则会先撞到 requirement 冗余一致性那道校验
    for item in valid_payload["match_board"]["items"]:
        if item["jd_requirement_id"] == "REQ-05":
            item["jd_requirement"] = "具备 5 年以上高并发场景架构演进经验"
    with pytest.raises(ValidationError) as exc:
        JDTargetedResumeReport.model_validate(valid_payload)
    msg = _validation_message(exc)
    assert "禁止在" in msg and "requirement 描述" in msg
