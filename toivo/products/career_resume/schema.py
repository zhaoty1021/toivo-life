"""
career_resume 业务线的 Pydantic 校验 schema。

对应 prompts/resume_v2.txt 的 JSON 输出规范。字段中文注释与 prompt 保持一致。
一旦 LLM 少字段 / 类型错 / 枚举乱, 这里会抛 ValidationError, 硬闸门会挡住 PDF。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator


# 允许模型演进时冗余字段过来, 不因新字段炸掉旧 pipeline
class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


# ---------------- 简介层 ----------------

class SubmissionReadiness(_Base):
    # 枚举与 prompt (resume_v2.txt:90) + 模板 (report.html:181-182 的 rd_class/rd_label) 一致
    status: Literal[
        "ready_to_submit",
        "needs_light_edit",
        "needs_substantial_revision",
        "needs_rewrite",
    ]
    reason: str
    minimum_changes_before_submit: List[str] = Field(default_factory=list)


class ExecutiveSummary(_Base):
    top_opportunities: List[str]
    top_blockers: List[str]
    this_week_focus: List[str]


class RadarEvidenceItem(_Base):
    dimension: str
    score: int = Field(ge=0, le=100)
    resume_evidence: str
    priority_fix: str


class MatchAnalysis(_Base):
    target_level: str
    competitive_positioning: str
    biggest_gap: str


class Strength(_Base):
    point: str
    evidence: str
    why_it_matters: str
    how_to_amplify: str


class Weakness(_Base):
    problem: str
    severity: Literal["high", "medium", "low"]
    # 收紧到 prompt (resume_v2.txt:141) 声明的枚举
    impact_area: Literal["screening", "interview", "offer_negotiation"]
    impact_explanation: str
    original_text: str
    why_this_reads_weak: str
    rewrite_type: Literal[
        "ready_to_use",         # 基于简历已有事实,可直接抄
        "needs_verification",   # 必须带 [待确认:] 占位符, 候选人补齐证据后再用
    ]
    rewrite: str
    facts_to_verify: List[str] = Field(default_factory=list)
    evidence_needed: str = ""
    # 收紧到 prompt (resume_v2.txt:149) 声明的枚举; 允许空串以保留 V1 兼容
    effort: Literal["", "low", "medium", "high"] = ""
    definition_of_done: str = ""
    interview_anchor: str = ""


class KeywordMatrixItem(_Base):
    keyword: str
    # 收紧到 prompt (resume_v2.txt:160) 声明的枚举
    #   must_show_for_target_role: 目标岗位必备, 必须让面试官一眼看到
    #   evidence_to_strengthen:    简历里已提, 但证据薄弱, 需强化
    #   add_only_if_true:          可加分, 但只在候选人真有事实时加
    #   do_not_force_add:          与目标岗位无关, 不要硬塞
    category: Literal[
        "must_show_for_target_role",
        "evidence_to_strengthen",
        "add_only_if_true",
        "do_not_force_add",
    ]
    resume_status: Literal["present_and_strong", "present_but_weak", "absent"]
    recommendation: str


class KeywordMatrix(_Base):
    context: str
    items: List[KeywordMatrixItem]


class StarUpgradeExample(_Base):
    original_bullet: str
    problem: str
    upgraded_version: str
    rewrite_type: Literal["ready_to_use", "needs_verification"]
    copy_ready_bullet: str
    interview_anchor: str = ""


class ProjectDeepDive(_Base):
    current_state: str
    star_upgrade_examples: List[StarUpgradeExample]


class InterviewQuestion(_Base):
    question: str
    why_it_will_be_asked: str
    # 强类型化: 兜住 LLM 偶尔吐字符串导致 Jinja `{% for step in ... %}` 逐字符迭代 → A4 爆版的坑。
    # answer_framework 必须是 list; validator 兜底把 "1) ... 2) ... 3) ..." 这种字符串切成 list。
    answer_framework: List[str] = Field(default_factory=list)
    facts_to_prepare: List[str] = Field(default_factory=list)
    avoid_saying: str

    @field_validator("answer_framework", "facts_to_prepare", mode="before")
    @classmethod
    def _coerce_string_to_list(cls, v: Any) -> Any:
        # 允许 LLM 偶尔吐字符串 —— 按 "1)" / "1." / "、" / "。" 切成 list, 不再让模板逐字符迭代。
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            # 优先按编号切: "1) foo 2) bar 3) baz" 或 "1. foo 2. bar"
            numbered = re.split(r"\s*\d+[\)\.、]\s*", s)
            parts = [p.strip() for p in numbered if p.strip()]
            if len(parts) >= 2:
                return parts
            # 否则按中文句号 / 分号切
            parts = re.split(r"[。；;]\s*", s)
            parts = [p.strip() for p in parts if p.strip()]
            return parts or [s]
        return v


class SevenDayItem(_Base):
    day: int = Field(ge=1, le=7)
    focus: str
    # actions 也是 list 型字段, 走同款 coerce, 防止 LLM 吐字符串 → 模板逐字符迭代 → A4 爆版
    actions: List[str] = Field(default_factory=list)
    definition_of_done: str
    expected_gain: str

    @field_validator("actions", mode="before")
    @classmethod
    def _coerce_string_to_list(cls, v: Any) -> Any:
        if isinstance(v, str):
            s = v.strip()
            if not s:
                return []
            numbered = re.split(r"\s*\d+[\)\.、]\s*", s)
            parts = [p.strip() for p in numbered if p.strip()]
            if len(parts) >= 2:
                return parts
            parts = re.split(r"[。；;]\s*", s)
            parts = [p.strip() for p in parts if p.strip()]
            return parts or [s]
        return v


# ---------------- 顶层报告 ----------------

class ResumeDiagnosis(_Base):
    """career_resume · 简历深度诊断报告 · V2 schema"""

    # 品牌元信息
    brand: str = "Toivo"
    product_line: str = "career"
    product_name: str = "简历深度诊断"
    series_no: str = "01"

    # 候选人基础信息
    candidate_name: str
    candidate_stage: str
    target_role: str
    target_company_or_industry: str = ""

    # 免责与定位
    scope_disclaimer: str = ""
    role_positioning: str

    # 总分与断言
    overall_score: int = Field(ge=0, le=100)
    score_calibration: str = ""
    one_line_verdict: str

    # 各章节
    submission_readiness: SubmissionReadiness
    executive_summary: ExecutiveSummary
    radar: Dict[str, int]
    radar_evidence: List[RadarEvidenceItem]
    match_analysis: MatchAnalysis
    strengths: List[Strength]
    weaknesses: List[Weakness]
    keyword_matrix: KeywordMatrix
    project_deep_dive: ProjectDeepDive
    interview_preparation: List[InterviewQuestion]
    seven_day_plan: List[SevenDayItem]

    # 结语
    final_words: str
    privacy_and_scope_note: str = ""
