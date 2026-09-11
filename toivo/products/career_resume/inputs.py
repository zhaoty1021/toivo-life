"""
career_resume 业务线的**输入模型**。

设计约束:
  · 每条业务自己定义"我需要哪些输入", 不假设跟简历业务一样只有一段文本。
  · CLI 从用户命令行收 dict → 交给 Product.run() → run() 用本模型 model_validate() 严格校验 → 传给 build_prompts。
  · Prompt 里的 {resume_text} / {target_role} / {target_company_or_industry} /
    {candidate_stage} 四个占位符全部对应到本模型的字段。

本业务**只做通用竞争力诊断**, 不做 JD 定制。JD 定制是独立业务包 jd_targeted_resume/,
有自己的 InputModel / prompt / schema / template。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CareerResumeInput(BaseModel):
    """career_resume 业务的输入。"""

    model_config = ConfigDict(extra="forbid")  # 输入侧严格 — 打错字段名要立刻报, 别静默吞

    resume_text: str = Field(min_length=20, description="候选人的简历原文 (纯文本)")

    target_role: str = Field(
        default="通用软件工程师方向",
        description="候选人瞄准的岗位方向 (用于给通用画像做锚点)",
    )

    target_company_or_industry: str = Field(
        default="",
        description="候选人瞄准的公司或行业范围 (可选)",
    )

    candidate_stage: str = Field(
        default="1-3 年",
        description="候选人所处阶段, 例: 校招 / 1-3 年 / 3-5 年 / 转行 / 重返职场",
    )
