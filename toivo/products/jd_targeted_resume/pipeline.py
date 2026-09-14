"""
jd_targeted_resume 业务流水线。

当前是**骨架版**: 只把 Product 契约填满 (input_model / accepted_input_modes /
build_prompts / parse_and_validate / build_render_context), 让 list-products
能识别、CLI 的 --inputs 通路能一路走到 InputModel 校验。

schema.py / prompts/jd_targeted_v1.txt / templates/report.* 会在后续任务里补齐。
现在如果真的跑 LLM, parse_and_validate 会直接 raise —— 这是想要的行为, 提醒
"这条业务线还没接通", 避免用户在下游看到误导性输出。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Tuple

from pydantic import BaseModel

from ..base import INPUT_MODE_JSON, Product
from .inputs import JDTargetedResumeInput


# 与 prompt 模板里的 {var} 一一对应。等 prompt 落地后, build_prompts 会逐个 str.replace
# 这些占位符 (不用 str.format —— JSON schema 里的花括号会打架)。
_PLACEHOLDERS = (
    "resume_text",
    "jd_text",
    "target_role",
    "target_company",
    "candidate_stage",
)


class JDTargetedResumeProduct(Product):
    """JD 定制简历策略报告 · 业务流水线 (骨架)."""

    product_dir = Path(__file__).parent
    input_model = JDTargetedResumeInput
    accepted_input_modes = frozenset({INPUT_MODE_JSON})

    _SYSTEM_PROMPT = (
        "你是面向技术岗位的招聘决策顾问与简历策略师。你的任务是**材料匹配诊断**, "
        "不是对候选人能力作事实判断。所有结论只允许基于本次输入的 JD 与简历原文, "
        "没有证据就标记为 not_evidenced 或 needs_verification, 禁止补脑。"
    )

    # ---------------- 契约方法 ----------------

    def build_prompts(self, inputs: JDTargetedResumeInput) -> Tuple[str, str]:
        """
        读取 prompt 模板, 逐个替换 5 个占位符, 并自检未替换项。

        当前 prompt 文件还未落地 (task 2.4), 这里先容忍 FileNotFoundError, raise 出
        业务化提示, 提醒调用方 "prompt 还没写好"。
        """
        prompt_path = self.product_dir / self.meta.prompt_file
        if not prompt_path.exists():
            raise RuntimeError(
                f"prompt 文件尚未创建: {prompt_path}\n"
                "  jd_targeted_resume 的 prompt 会在 task 2.4 里补齐; "
                "在此之前请只用 --from-json 走重渲染路径 (需要有一份合法的报告 JSON)。"
            )
        template = prompt_path.read_text(encoding="utf-8")

        values = {
            "resume_text": inputs.resume_text.strip(),
            "jd_text": inputs.jd_text.strip(),
            "target_role": inputs.target_role,
            "target_company": inputs.target_company,
            "candidate_stage": inputs.candidate_stage,
        }

        user = template
        for name in _PLACEHOLDERS:
            user = user.replace("{" + name + "}", values[name])

        # 自检: 如果模板里有我们不认识的 {something}, 或者有的占位符没被填 (values 缺项),
        # 直接抛错。宁可让开发者早点看到, 也别让字面 "{jd_text}" 溜进 LLM 输入。
        leftover = [n for n in _PLACEHOLDERS if "{" + n + "}" in user]
        if leftover:
            raise RuntimeError(f"prompt 模板替换后仍残留占位符: {leftover}")

        return self._SYSTEM_PROMPT, user

    def parse_and_validate(self, raw_text: str) -> Any:
        """
        待 schema.py (task 2.3) 落地后, 这里会:
          1. 从 raw_text 里剥出 JSON (处理 ```json ... ``` 包裹)
          2. JDTargetedResumeReport.model_validate_json(...)
          3. 补 pipeline 派生字段 (Match Board 计数, 报告编号, 交付日期)
        当前先 raise, 避免拿到"看起来能跑但没校验"的假输出。
        """
        raise NotImplementedError(
            "jd_targeted_resume.schema 尚未落地 (task 2.3)。"
            " 想先看模板效果请用 --from-json + 已经生成好的报告 JSON。"
        )

    def build_render_context(
        self, data: Any, toc_pages: Dict[str, int]
    ) -> Dict[str, Any]:
        """
        待 templates/report.html (task 2.6) 落地后填充真实上下文。
        """
        raise NotImplementedError(
            "jd_targeted_resume 的报告模板尚未落地 (task 2.6)。"
        )
