"""
career_resume 业务线的 Product 子类。

只做三件事:
  1. build_prompts: 把 CareerResumeInput 的字段填进 prompts/resume_v2.txt 的 4 个占位符
  2. parse_and_validate: JSON 解析 + Pydantic 校验 (ResumeDiagnosis)
  3. build_render_context: data + radar_svg + report_no/date + toc_pages → 模板上下文

其余流水线由 Product 基类的 run() 统一处理。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from ..base import Product
from ...render.jinja_filters import build_radar_svg
from .inputs import CareerResumeInput
from .schema import ResumeDiagnosis


# prompt 里用 {var} 单花括号占位; JSON schema 部分用 {{}} 双花括号。
# 用 str.replace 精确替换 4 个已知占位符 —— 不能用 str.format, 会把 JSON schema 的 {{
# 也当成转义处理; 也不用 Jinja, prompt 里的花括号会跟 Jinja {{ }} 语法冲突。
_PLACEHOLDERS = (
    "resume_text",
    "target_role",
    "target_company_or_industry",
    "candidate_stage",
)


class CareerResumeProduct(Product):
    product_dir = Path(__file__).parent
    input_model = CareerResumeInput

    # ------------- 1. prompt 拼装 -------------

    _SYSTEM_PROMPT = (
        "你是 Toivo 简历深度诊断服务的核心分析师。严格按用户消息中的 JSON schema 输出,"
        "不要包裹 markdown 代码块,不要输出任何 JSON 之外的字符。所有中文按简体中文,"
        "标点使用中文标点。"
    )

    def build_prompts(self, inputs: CareerResumeInput) -> Tuple[str, str]:
        prompt_path = self.product_dir / self.meta.prompt_file
        template = prompt_path.read_text(encoding="utf-8")

        # 把 4 个占位符一次性替换掉 —— strip 只针对 resume_text 这类长文本,
        # 其它字段可能有意义的前后空格保留
        values = {
            "resume_text": inputs.resume_text.strip(),
            "target_role": inputs.target_role,
            "target_company_or_industry": inputs.target_company_or_industry,
            "candidate_stage": inputs.candidate_stage,
        }
        user = template
        for name in _PLACEHOLDERS:
            user = user.replace("{" + name + "}", values[name])

        # 兜底自检: 如果 prompt 里少了某个 {var} 占位, 简历原文就会丢
        # (人工改 prompt 时最容易犯的错), 直接抛出来
        missing = [n for n in _PLACEHOLDERS if "{" + n + "}" in template and values[n] not in user]
        if missing:
            raise RuntimeError(
                f"prompt 模板替换后仍残留占位符 (values 里没填?): {missing}"
            )

        return self._SYSTEM_PROMPT, user

    # ------------- 2. 解析 + 校验 -------------

    def parse_and_validate(self, raw_text: str) -> ResumeDiagnosis:
        text = raw_text.strip()
        # 容错: LLM 偶尔会包 ```json ... ```
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        payload = json.loads(text)
        return ResumeDiagnosis.model_validate(payload)

    # ------------- 3. 渲染上下文 -------------

    def build_render_context(
        self,
        data: ResumeDiagnosis,
        toc_pages: Dict[str, int],
    ) -> Dict[str, Any]:
        # 模板全程按 dict 访问 (data.radar['技术呈现'] 之类), 保持兼容 → 转 dict
        data_dict = data.model_dump()
        now = datetime.now()
        return {
            "data": data_dict,
            "radar_svg": build_radar_svg(data_dict["radar"]),
            "report_no": now.strftime("%Y%m%d%H%M"),
            "report_date": now.strftime("%Y.%m.%d"),
            "toc_pages": toc_pages,
        }
