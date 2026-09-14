"""
jd_targeted_resume · 输入模型。

JD 定制版是**独立业务包**, 不是 career_resume 的一个 mode。它面向"我要投这份具体
JD, 简历应该怎么改"的场景, 判断基准是用户提交的 JD 原文, 不是通用招聘画像。

必填输入 3 项: resume_text / jd_text / target_role。
可选补充 2 项: target_company / candidate_stage (用于校准语气与岗位级别)。

CLI 入口是 `--inputs <case.json>` (多字段 JSON), 不接受 `--input <单文本>`。
Product 层通过 `accepted_input_modes = {"json"}` 让 CLI 提前拒错入口。
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class JDTargetedResumeInput(BaseModel):
    """jd_targeted_resume 业务的输入。

    input 侧 `extra="forbid"` —— 字段名写错立即报错, 不要让 CLI JSON 里的错别字
    静默漏进 LLM 提示词 (会造成幽灵字段 + 双喂 bug)。
    """

    model_config = ConfigDict(extra="forbid")

    resume_text: str = Field(
        min_length=20,
        description="候选人的简历原文 (纯文本)",
    )

    jd_text: str = Field(
        min_length=80,
        description=(
            "目标岗位 JD 原文 (纯文本)。至少 80 字符, 排除只有几句宣传语的伪 JD —— "
            "缺少足够信号的 JD 会让证据匹配退化为关键词计数, 报告价值大幅下降。"
        ),
    )

    target_role: str = Field(
        min_length=2,
        description=(
            "候选人瞄准的岗位名称, 例: 'Java 后端开发工程师' / '数据平台工程师'。"
            "用于报告封面, 也帮助 LLM 明确对齐方向。"
        ),
    )

    target_company: str = Field(
        default="",
        description="目标公司或部门 (可选)。会出现在报告封面, 也用于校准语气。",
    )

    candidate_stage: str = Field(
        default="",
        description=(
            "候选人所处阶段 (可选), 例: 校招 / 1-3 年 / 3-5 年 / 转行 / 重返职场。"
            "用于校准岗位级别期望, 不影响是否投递的判断基准。"
        ),
    )
