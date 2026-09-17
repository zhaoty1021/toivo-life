"""
jd_targeted_resume 业务线的 Product 子类。

只做三件事:
  1. build_prompts: 把 JDTargetedResumeInput 的 5 个字段填进 prompts/jd_targeted_v1.txt
  2. parse_and_validate: JSON 解析 + Pydantic 校验 (JDTargetedResumeReport)
  3. build_render_context: data + 派生统计 (Match Board 各态计数、blocker 分级) → 模板上下文

其余流水线由 Product 基类的 run() 统一处理。

## 与 career_resume pipeline 的差异

- 输入字段 5 个 (vs 4 个), 但拼装机制完全一致 (str.replace 精确替换 5 个占位符)
- **没有雷达图 SVG** —— JD 定制版视觉重心是 Match Board 三色矩阵, 而不是六维雷达
- **派生了 Match Board 汇总统计** 在 build_render_context 里, 让模板不用做 for-count 二次遍历
- Report metadata (report_no / report_date) 逻辑与 career_resume 一致, 便于两条产品线共享封面样式
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from ..base import INPUT_MODE_JSON, Product
from .inputs import JDTargetedResumeInput
from .schema import (
    JDTargetedResumeReport,
    PRIVACY_AND_SCOPE_NOTE_TEXT,
    SCOPE_DISCLAIMER_TEXT,
)


# prompt 里 {var} 是单花括号占位符; JSON schema 例子里的 {{}} 是双花括号 (要保留)。
# 精确 str.replace 5 个占位符; 不能用 str.format —— JSON schema 的 {{}} 会打架。
_PLACEHOLDERS = (
    "resume_text",
    "jd_text",
    "target_role",
    "target_company",
    "candidate_stage",
)


class JDTargetedResumeProduct(Product):
    """JD 定制简历策略报告 · 业务流水线."""

    product_dir = Path(__file__).parent
    input_model = JDTargetedResumeInput
    accepted_input_modes = frozenset({INPUT_MODE_JSON})

    _SYSTEM_PROMPT = (
        "你是面向技术岗位的招聘决策顾问与简历策略师。你的任务是**材料匹配诊断**, "
        "不是对候选人能力作事实判断。所有结论只允许基于本次输入的 JD 与简历原文, "
        "没有证据就标记为 not_evidenced 或 needs_verification, 禁止补脑。"
        "严格按用户消息中的 JSON schema 输出, 不要包裹 markdown 代码块, "
        "不要输出任何 JSON 之外的字符。中文使用简体中文, 标点使用中文标点。"
    )

    # ------------- 1. prompt 拼装 -------------

    def build_prompts(self, inputs: JDTargetedResumeInput) -> Tuple[str, str]:
        prompt_path = self.product_dir / self.meta.prompt_file
        if not prompt_path.exists():
            # 保留为业务化异常, 让 CLI 层能给出"哪个业务的 prompt 还没写"的清晰指示
            raise RuntimeError(
                f"prompt 文件缺失: {prompt_path}\n"
                "  jd_targeted_resume 的 prompt 应位于该路径; "
                "在此之前请只用 --from-json 走重渲染路径。"
            )
        template = prompt_path.read_text(encoding="utf-8")

        # strip 只针对长文本 (resume_text / jd_text), 其它字段可能带有意义的空格保留原样
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

        # 兜底自检: 如果拼装后还残留任何一个占位符, 说明模板漏了或改动了变量名 —— 立即抛,
        # 不能让字面 "{jd_text}" 溜进 LLM prompt。
        leftover = [n for n in _PLACEHOLDERS if "{" + n + "}" in user]
        if leftover:
            raise RuntimeError(f"prompt 模板替换后仍残留占位符: {leftover}")

        return self._SYSTEM_PROMPT, user

    # ------------- 2. 解析 + 校验 -------------

    def parse_and_validate(self, raw_text: str) -> JDTargetedResumeReport:
        """
        解析 LLM 输出 → 校验 → 返回 JDTargetedResumeReport 实例。

        校验失败 (schema 违规 / id 引用断裂 / rewrite 真实性红线破了) 一律直接 raise,
        由基类 Product.run() 让 CLI 打出栈, 不生成误导性 PDF。
        """
        text = raw_text.strip()
        # LLM 偶尔会包 ```json ... ``` 或裸 ``` —— 容错剥掉
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        payload = json.loads(text)
        return JDTargetedResumeReport.model_validate(payload)

    # ------------- 3. 渲染上下文 -------------

    def build_render_context(
        self,
        data: JDTargetedResumeReport,
        toc_pages: Dict[str, int],
    ) -> Dict[str, Any]:
        """
        产出 Jinja2 上下文 dict。模板全程按 dict 语义访问, 保持与 career_resume 一致。

        除了原始 data 之外, 这里预先算好 5 组派生统计, 让模板不需要在渲染时做
        for-count/if-count 二次遍历 (那样容易触发页面重排):

        - match_board_summary: 四种 status 的计数 —— 用于 Match Board 顶部汇总胶囊
        - must_have_blocker_summary: 三种 severity 的计数 —— 用于硬门槛封面
        - priority_gap_summary: 计数 —— 用于优先强化区块
        - inferred_risk_summary: 计数按 confidence 分 —— 用于语境推断风险区块
        - rewrite_summary: 两种 rewrite_type 的计数 —— 用于改写卡章节封面
        - requirement_summary: 四种 requirement_type 的计数 —— 用于 JD 解构章节

        同时**强制覆盖** data_dict.meta.scope_disclaimer 与 data_dict.privacy_and_scope_note
        为服务端定义的常量。这两段是合规声明, 不允许 LLM 自由发挥 (哪怕 prompt 里已经硬
        约束了固定文本, 这一层是最后的护栏)。
        """
        data_dict = data.model_dump()
        now = datetime.now()

        # -------- 服务端常量覆盖 (合规护栏) --------
        # 无论 LLM 输出什么, scope_disclaimer / privacy_and_scope_note 一律替换为常量。
        # 出错宁可让 KeyError 抛出来 (schema 契约已强制这两个字段存在), 不做默默 setdefault。
        data_dict["meta"]["scope_disclaimer"] = SCOPE_DISCLAIMER_TEXT
        data_dict["privacy_and_scope_note"] = PRIVACY_AND_SCOPE_NOTE_TEXT

        # -------- 派生统计 (不改动源数据) --------
        board_items = data_dict["match_board"]["items"]
        match_board_summary = {
            "total": len(board_items),
            "matched": sum(1 for i in board_items if i["status"] == "matched"),
            "weakly_matched": sum(1 for i in board_items if i["status"] == "weakly_matched"),
            "not_evidenced": sum(1 for i in board_items if i["status"] == "not_evidenced"),
            "missing": sum(1 for i in board_items if i["status"] == "missing"),
        }

        # 三段风险分层的各自汇总 (Phase 1 拆分):
        # must_have_blocker: 硬门槛, 有 severity
        # priority_gap: 优先强化, 有 severity
        # inferred_risk: 语境推断, 无 severity, 但有 confidence (low/medium)
        blockers = data_dict.get("must_have_blockers", [])
        must_have_blocker_summary = {
            "total": len(blockers),
            "high": sum(1 for b in blockers if b["severity"] == "high"),
            "medium": sum(1 for b in blockers if b["severity"] == "medium"),
            "low": sum(1 for b in blockers if b["severity"] == "low"),
        }
        # 向后兼容别名 —— 老模板变量, 逐步迁移中
        blocker_summary = must_have_blocker_summary

        gaps = data_dict.get("priority_gaps", [])
        priority_gap_summary = {
            "total": len(gaps),
            "high": sum(1 for g in gaps if g["severity"] == "high"),
            "medium": sum(1 for g in gaps if g["severity"] == "medium"),
            "low": sum(1 for g in gaps if g["severity"] == "low"),
        }

        risks = data_dict.get("inferred_risks", [])
        inferred_risk_summary = {
            "total": len(risks),
            "medium": sum(1 for r in risks if r["confidence"] == "medium"),
            "low": sum(1 for r in risks if r["confidence"] == "low"),
        }

        cards = data_dict["rewrite_cards"]
        rewrite_summary = {
            "total": len(cards),
            "ready_to_use": sum(1 for c in cards if c["rewrite_type"] == "ready_to_use"),
            "needs_verification": sum(1 for c in cards if c["rewrite_type"] == "needs_verification"),
        }

        reqs = data_dict["jd_requirements"]
        requirement_summary = {
            "total": len(reqs),
            "must_have": sum(1 for r in reqs if r["requirement_type"] == "must_have"),
            "preferred": sum(1 for r in reqs if r["requirement_type"] == "preferred"),
            "nice_to_have": sum(1 for r in reqs if r["requirement_type"] == "nice_to_have"),
            "inferred_from_context": sum(1 for r in reqs if r["requirement_type"] == "inferred_from_context"),
        }

        return {
            "data": data_dict,
            "match_board_summary": match_board_summary,
            "must_have_blocker_summary": must_have_blocker_summary,
            "priority_gap_summary": priority_gap_summary,
            "inferred_risk_summary": inferred_risk_summary,
            "blocker_summary": blocker_summary,  # 兼容旧模板名, 后续迁移
            "rewrite_summary": rewrite_summary,
            "requirement_summary": requirement_summary,
            "report_no": now.strftime("%Y%m%d%H%M"),
            "report_date": now.strftime("%Y.%m.%d"),
            "toc_pages": toc_pages,
        }
