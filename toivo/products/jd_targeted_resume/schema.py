"""
jd_targeted_resume 业务线的 Pydantic 校验 schema。

对应 prompts/jd_targeted_v1.txt 的 JSON 输出规范。所有字段中文注释与 prompt 保持一致。
LLM 少字段 / 类型错 / 枚举乱 → ValidationError, 硬闸门挡在渲染前, 不生成误导性 PDF。

## 与 career_resume 的关键区别

career_resume 判断基准是**通用招聘画像**; jd_targeted_resume 的一切判断都必须**只**基于
用户本次提交的 JD 原文与简历原文。schema 里的一系列 Literal 枚举 + 关系一致性校验器,
就是把"补脑""泛化推演""无证据判断"这些常见 LLM 失败模式当作数据结构层的硬约束。

## 6 组核心 Literal 枚举 (硬红线)

1. SubmitVerdict          —— 投递可行性四档 (submit_now → do_not_submit)
2. MatchStatus            —— JD 每条要求在简历中的匹配态 (matched / weakly_matched /
                              not_evidenced / missing)
3. RequirementType        —— JD 每条要求的性质 (must_have / nice_to_have / preferred /
                              inferred_from_context)
4. RewriteType            —— 每条改写是否可直接使用 (ready_to_use /
                              needs_verification)
5. Severity               —— high / medium / low, 用于 blocker / gap / risk 分级
6. InferenceConfidence    —— inferred_from_context 类要求的推断置信度 (low / medium)
                              —— 显式不允许 high, 防止把猜测包装成事实

## 三段风险分层 (Phase 1 语义修正)

原先所有"未 matched"的问题都塞进 must_have_blockers, 会把 preferred/nice_to_have
的差距误报为"硬门槛", 用户读起来会以为投不了。修正后拆成三段, 严格按 requirement_type
入组:

- must_have_blockers  → 只允许指向 must_have 要求 · 严重级投递阻挡
- priority_gaps       → 只允许指向 preferred / nice_to_have 要求 · 影响竞争力但不阻投
- inferred_risks      → 只允许指向 inferred_from_context 要求 · 供核实, 不作否决

## 一致性校验器

- must_have_blockers / priority_gaps / inferred_risks 三段各自锁死允许的 requirement_type,
  违反即 raise —— 让 "把 preferred 报成硬门槛" 这类漂移在 schema 层就死掉。
- must_have_blockers[i].linked_rewrite_card_id 是 **必填**, 且引用的 RewriteCard.targets
  必须包含该 blocker 的 jd_requirement_id —— 强制 blocker → 改写 → 证据的行动闭环。
- Match Board 与 jd_requirements 严格一一对应且 id 唯一 (不能重复不能漏)。
- rewrite_cards / evidence_collection.items 的 id 全局唯一。
- rewrite_cards 里每条 rewrite_type=needs_verification 的必须带 `[待确认: ...]` 占位符
  且 evidence_needed 非空; ready_to_use 反过来不许出现占位符。
- evidence_collection.items 里每条必须至少绑定一个 jd_requirement (来源) 或一个
  rewrite_card_id (去向), 避免"孤儿证据"污染报告。
- inferred_from_context 类要求禁止在 requirement 描述里出现具体数字/年限/职级
  (由 prompt 层控制 + schema 层的 _forbid_numeric_inference regex 兜底)。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ================================================================
# 通用容器: 允许 LLM 冗余字段冒出 (extra="allow") —— 但每个业务子模型都会用具体
# Field 约束把关键路径锁死, 冗余只体现在末梢文本字段。
# ================================================================

class _Base(BaseModel):
    model_config = ConfigDict(extra="allow")


# ================================================================
# 枚举定义 —— 用类型别名的方式集中在一处, 出问题时容易定位到源头
# ================================================================

SubmitVerdict = Literal[
    "submit_now",                 # 简历已足够 fit 这份 JD, 可立即投
    "submit_after_light_edit",    # 局部改写后即可投 (<30 分钟工作量)
    "submit_after_rewrite",       # 有实质性 gap, 需要证据补充或段落重写才建议投
    "do_not_submit",              # JD 与候选人材料错配严重, 建议改投其他岗位
]

MatchStatus = Literal[
    "matched",          # 简历原文有明确证据支撑
    "weakly_matched",   # 简历里有边缘信号, 但未突出 / 未量化 / 埋在名词堆里
    "not_evidenced",    # 简历里没写, 但候选人可能有 (需候选人补证据)
    "missing",          # 简历没写, 且从材料上看候选人也确实没做过
]

RequirementType = Literal[
    "must_have",              # JD 明确写"必须""要求""精通"或以硬门槛形式出现
    "nice_to_have",           # JD 用"加分""优先""熟悉"等修饰
    "preferred",              # JD 用"最好""期望", 弱于 must_have 但强于 nice_to_have
    "inferred_from_context",  # JD 未明写, 但基于岗位场景合理推断 (必须标出推断依据)
]

RewriteType = Literal[
    "ready_to_use",          # 基于简历已有事实即可, 可直接抄
    "needs_verification",    # 必须带 [待确认: ...] 占位符 + evidence_needed
]

Severity = Literal["high", "medium", "low"]

InferenceConfidence = Literal["low", "medium"]
#: 显式没有 "high" —— 语境推断的置信度上限是 medium, 防止把猜测包装成事实。


_PLACEHOLDER_PAT = re.compile(r"\[\s*待确认\s*:")

#: 服务端注入的固定文案 (Phase 1 修正: 不再让 LLM 自由输出这两段)
#: 见 pipeline.build_render_context —— 会强制覆盖 meta.scope_disclaimer 与
#: 顶层 privacy_and_scope_note。这里保留常量供 schema.py / 模板双方共享。
SCOPE_DISCLAIMER_TEXT = (
    "本报告基于用户提交的 JD 原文与简历原文生成, 不代表招聘公司实际筛选标准, "
    "不含任何背景调查。当前版本交付投递策略、可替换文案与证据核验清单, "
    "暂不生成排版完成的最终简历文件。"
)
PRIVACY_AND_SCOPE_NOTE_TEXT = (
    "本报告基于候选人主动提交的 JD 与简历文本生成, 不含任何背景调查、征信、"
    "社交媒体或第三方数据。所有判断均基于呈现层匹配, 不构成对候选人实际能力、"
    "职业选择或人格特质的评价。"
)

#: 数字 / 年限 / 职级 / 金额等具体阈值 —— inferred_from_context 类要求禁止出现。
#: 例: "万级 QPS", "5 年经验", "P7 及以上", "百万 DAU" 都会被这条兜底 regex 拦下。
_INFERRED_NUMERIC_PAT = re.compile(
    r"(?:\d+\s*(?:年|万|亿|千|百|QPS|qps|DAU|dau|MAU|mau|人|台|次)"
    r"|[PpTtEeMm]\s*\d+"                       # P7 / T3 / E4 / M5 职级
    r"|(?:万|亿|千|百|十)\s*(?:级|亿|万))"
)


# ================================================================
# 元信息层
# ================================================================

class ReportMeta(_Base):
    """封面 + 定位声明。所有诊断报告都必须显式声明本次判断的基准是"这份 JD"而非通用画像。"""

    brand: str = "Toivo"
    product_line: str = "career"
    product_name: str = "JD 定制简历策略报告"
    series_no: str = "02"

    candidate_name: str
    target_role: str
    target_company: str = ""
    candidate_stage: str = ""

    #: 固定文案, 用于报告开头声明判断基准 —— 与 career_resume 的 scope_disclaimer 相反。
    #: career_resume 说"基于通用画像"; 这里必须说"仅基于用户提交的这份 JD"。
    scope_disclaimer: str = ""


# ================================================================
# 投递判断层
# ================================================================

class SubmitDecision(_Base):
    """投递可行性判断 + 一句话理由 + 关键前置条件。"""

    verdict: SubmitVerdict
    #: 数值型 fit 分, 0-100。评估的是"这份简历 ↔ 这份 JD 的匹配呈现质量", 不是能力分。
    fit_score: int = Field(ge=0, le=100)
    #: 分数说明, 强调这是"呈现层匹配度", 避免被误读为"你能不能干这个活"。
    score_calibration: str = ""
    #: 一句话核心结论。可直接、可扎心, 但落点必须在"要不要投 / 投前做什么"。
    one_line_verdict: str
    #: 若 verdict != submit_now, 列出投递前最少要处理的 2-4 条 action。
    minimum_actions_before_submit: List[str] = Field(default_factory=list)


# ================================================================
# JD 结构化解构 —— 让下游 Match Board 有清晰的锚点
# ================================================================

class JDRequirement(_Base):
    """从 JD 原文里抽出的一条要求, 是 Match Board 的行主键。"""

    #: 稳定的 id (如 REQ-01, REQ-02), 便于交叉引用 rewrite_card / blocker / evidence 项。
    id: str = Field(min_length=1)
    #: 一句话描述这条要求
    requirement: str
    requirement_type: RequirementType
    #: JD 原文中的具体位置或短语引用 —— 每条抽出的要求必须能指回原文, 不能凭空发挥。
    jd_evidence: str
    #: 若 requirement_type=inferred_from_context, 必须写清推断依据; 其他类型可为空。
    inference_note: str = ""
    #: 若 requirement_type=inferred_from_context, 必须给出置信度; 其他类型忽略此字段。
    #: 只允许 low / medium —— 语境推断不允许 high, 防止把猜测包装成事实。
    inference_confidence: Optional[InferenceConfidence] = None

    @model_validator(mode="after")
    def _check_inference_note(self) -> "JDRequirement":
        if self.requirement_type == "inferred_from_context":
            if not self.inference_note.strip():
                raise ValueError(
                    f"JDRequirement {self.id}: requirement_type=inferred_from_context "
                    f"必须在 inference_note 里写清是根据 JD 哪一段推断出来的, 不能凭空加要求"
                )
            if self.inference_confidence is None:
                raise ValueError(
                    f"JDRequirement {self.id}: inferred_from_context 类要求必须给出 "
                    f"inference_confidence (low / medium)"
                )
            # 兜底: 推断项 requirement 描述禁止出现具体数字 / 年限 / 职级阈值。
            # 让模型把 "承接高并发服务" 这类语义要求归为 inferred, 而把 "万级 QPS" 这类数字
            # 阈值留给候选人自己去核实 —— 这是防止模型把猜测包装成事实的最后一道兜底。
            if _INFERRED_NUMERIC_PAT.search(self.requirement):
                raise ValueError(
                    f"JDRequirement {self.id}: inferred_from_context 类要求禁止在 "
                    f"requirement 描述中出现具体数字/年限/职级阈值 (如 万级 QPS / 5 年经验 / "
                    f"P7 及以上); 请把数字层信息留给 JD 明示要求或候选人核实, requirement "
                    f"文本应停留在语义层。当前 requirement={self.requirement!r}"
                )
        return self


# ================================================================
# Match Board —— 报告核心可视化
# ================================================================

class MatchBoardItem(_Base):
    """Match Board 的一行: 一条 JD 要求 × 简历里的证据 × 状态判断。"""

    #: 引用 JDRequirement.id
    jd_requirement_id: str = Field(min_length=1)
    #: 冗余拷贝一份 requirement 文本, 让模板不用做二次查表
    jd_requirement: str
    requirement_type: RequirementType
    status: MatchStatus
    #: 简历原文里对应这条要求的引用片段。status=missing/not_evidenced 时允许为空字符串。
    resume_evidence: str = ""
    #: 一句话评价这一格的匹配态 —— 例: "简历只列了 Kafka 名词, 未体现消息驱动架构设计经验"
    gap_note: str


class MatchBoard(_Base):
    """所有 JD 要求 × 简历的对齐总表。渲染成一张三色矩阵。"""

    #: 一句话说明本 Board 的判断基准 (固定强调"基于本次 JD, 不是通用画像")
    context: str
    items: List[MatchBoardItem]

    @model_validator(mode="after")
    def _check_non_empty(self) -> "MatchBoard":
        if not self.items:
            raise ValueError("MatchBoard.items 不能为空 —— 至少要抽出一条 JD 要求做对齐")
        # 冗余字段一致性: item.requirement_type 应该与其 jd_requirement_id 指向的
        # JDRequirement.requirement_type 一致 —— 但 MatchBoard 本身拿不到 JDRequirement,
        # 这一步在 JDTargetedResumeReport 顶层统一校验。
        return self


# ================================================================
# Must-Have Blockers —— 会挡在筛简历环节的硬伤
# ================================================================

# ================================================================
# 三段风险分层 (Phase 1 语义修正)
#
# 原先所有"未 matched"问题都塞 must_have_blockers, 会把 preferred 差距误报为硬门槛。
# 修正后按 requirement_type 分成三段, 语义清晰:
#
#   MustHaveBlocker  →  must_have          (硬门槛, 不处理不建议投)
#   PriorityGap      →  preferred / nice   (影响竞争力, 但不阻投)
#   InferredRisk     →  inferred           (供核实, 不作否决依据)
#
# 每段只允许指向对应类型的 requirement, 顶层 validator 会做交叉检查。
# ================================================================

class MustHaveBlocker(_Base):
    """
    硬门槛风险 —— 必须处理, 不处理就不建议投。

    只允许指向 requirement_type=must_have 的要求。
    linked_rewrite_card_id 是**必填**, 必须闭环到一张改写卡。
    """

    #: 引用 JDRequirement.id —— 顶层校验会验证:
    #: (1) 该 id 对应的 requirement_type 必须是 must_have
    #: (2) 该 id 在 match_board 里对应的 status 必须是 weakly_matched / not_evidenced /
    #:     missing 之一, 不能是 matched
    jd_requirement_id: str = Field(min_length=1)
    problem: str                # 一句话问题标题
    severity: Severity
    #: 若不处理, 会在筛简历 / 电面 / 终面 / offer 谈判的哪一步失败
    impact_stage: Literal["screening", "phone_screen", "onsite", "offer"]
    impact_explanation: str
    #: 建议的处理动作 —— 简短可执行, 展开细节放在关联的 rewrite_card 里
    recommended_action: str
    #: 关联的 rewrite_card id —— **必填**, 强制 blocker → 改法闭环。顶层 validator 会
    #: 校验此 id 存在于 rewrite_cards, 且该卡的 targets_requirement_ids 包含本
    #: blocker 的 jd_requirement_id。
    linked_rewrite_card_id: str = Field(min_length=1)


class PriorityGap(_Base):
    """
    优先强化项 —— 影响竞争力, 但不阻挡投递。

    只允许指向 requirement_type ∈ {preferred, nice_to_have} 的要求。
    linked_rewrite_card_id 可选 (差距未必都有对应改法, 有些是长期能力建设)。
    """

    jd_requirement_id: str = Field(min_length=1)
    problem: str
    severity: Severity
    #: 影响的是 竞争力对比 / 面试深度追问, 而非硬门槛; 用户可见文案强调"可投, 但..."
    impact_stage: Literal["screening", "phone_screen", "onsite", "offer"]
    impact_explanation: str
    recommended_action: str
    #: 可选, 不强制闭环 (有些 preferred 差距只能靠时间积累, 不适合造改写卡)
    linked_rewrite_card_id: str = ""


class InferredRisk(_Base):
    """
    语境推断风险 —— 从 JD 上下文推断的隐性要求, 供候选人核实, 不作否决依据。

    只允许指向 requirement_type=inferred_from_context 的要求。
    没有 severity 字段 —— 推断项不谈严重性, 只谈是否需要主动核实。
    """

    jd_requirement_id: str = Field(min_length=1)
    #: 一句话说清"这是从 JD 哪一段推断出来的什么可能要求" (面向候选人的推断信号叙述)
    risk_note: str
    #: 复用 JDRequirement.inference_confidence, 用户可见时视觉降级
    confidence: InferenceConfidence
    #: 建议候选人如何核实 (面试问 HR / 看公司技术博客 / 内推打听 …)
    #: 与 MustHaveBlocker.recommended_action 有意区分命名: 推断项不谈"应处理", 只谈"应核实"
    verify_hint: str
    linked_rewrite_card_id: str = ""


# ================================================================
# Rewrite Cards —— 报告的落地价值担当: 可直接复制的文案改写
# ================================================================

class RewriteCard(_Base):
    """一段可直接替换到简历里的文案卡。"""

    id: str = Field(min_length=1)          # 稳定 id, 例 RW-01
    #: 定位简历里的哪一段 (例: "阿里云实习 · bullet 2" / "项目经历 · 工业视觉平台 · bullet 3")
    resume_section: str
    #: 简历原文 (Before)
    original_text: str
    #: 改写目标: 想凸显 JD 里的哪几条要求, 引用 JDRequirement.id 列表
    targets_requirement_ids: List[str] = Field(default_factory=list)
    rewrite_type: RewriteType
    #: 改写后的可直接使用文案 (After)
    rewritten_text: str
    #: needs_verification 类型必须列: 需要候选人补的具体事实清单
    evidence_needed: List[str] = Field(default_factory=list)
    #: 面试官最可能针对这条改写追问的一个点, 让候选人提前预判
    interview_anchor: str

    # ---------- 真实性规则 (硬红线) ----------
    @model_validator(mode="after")
    def _check_truthfulness(self) -> "RewriteCard":
        rewritten = self.rewritten_text or ""
        has_placeholder = bool(_PLACEHOLDER_PAT.search(rewritten))
        if self.rewrite_type == "needs_verification":
            if not has_placeholder:
                raise ValueError(
                    f"RewriteCard {self.id}: rewrite_type=needs_verification 的 rewritten_text "
                    f"必须包含 `[待确认: 具体描述]` 占位符, 不允许把不确定的数字硬写实。"
                )
            if not self.evidence_needed:
                raise ValueError(
                    f"RewriteCard {self.id}: needs_verification 必须在 evidence_needed 里列出 "
                    f"候选人要补的具体事实, 不能空数组。"
                )
        else:  # ready_to_use
            if has_placeholder:
                raise ValueError(
                    f"RewriteCard {self.id}: rewrite_type=ready_to_use 的 rewritten_text 不允许 "
                    f"再出现 `[待确认: ...]` 占位符; 如果需要待确认, 请改成 needs_verification。"
                )
        return self

    @field_validator("targets_requirement_ids", mode="before")
    @classmethod
    def _coerce_ids(cls, v: Any) -> Any:
        # 兜住 LLM 偶尔把 id list 吐成单字符串的坑
        if isinstance(v, str):
            v = v.strip()
            return [x.strip() for x in re.split(r"[,, ；;]", v) if x.strip()]
        return v


# ================================================================
# 证据收集 —— 候选人投递前需要主动补齐的信息清单
# ================================================================

class EvidenceCollectionItem(_Base):
    """"候选人下班后要打开备忘录做的事" —— 每条都必须有源头 (JD 要求) 或去向 (rewrite card)。"""

    id: str = Field(min_length=1)
    #: 要收集/核实的具体事实 (一句话, 可执行)
    ask: str
    #: 为什么要收集这个 —— 关联到哪条 JD 要求或哪张改写卡
    linked_requirement_ids: List[str] = Field(default_factory=list)
    linked_rewrite_card_ids: List[str] = Field(default_factory=list)
    #: 建议的收集途径 (监控系统 / 前主管 / 项目文档 / commit 记录 …)
    where_to_get: str
    #: 优先级: 挡投递 = high (must-have blocker 派生), 强化材料 = medium, 面试用 = low
    priority: Severity

    @field_validator("linked_requirement_ids", "linked_rewrite_card_ids", mode="before")
    @classmethod
    def _coerce_ids(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            return [x.strip() for x in re.split(r"[,, ；;]", v) if x.strip()]
        return v

    @model_validator(mode="after")
    def _check_has_linkage(self) -> "EvidenceCollectionItem":
        # 每条证据必须至少有一个源头或去向; 否则就是"孤儿证据", 报告等于没用。
        if not self.linked_requirement_ids and not self.linked_rewrite_card_ids:
            raise ValueError(
                f"EvidenceCollectionItem {self.id}: 至少要绑定一个 linked_requirement_id "
                f"或一个 linked_rewrite_card_id, 不允许孤儿证据条目。"
            )
        return self


class EvidenceCollection(_Base):
    """证据清单总容器。"""

    context: str = ""
    items: List[EvidenceCollectionItem] = Field(default_factory=list)


# ================================================================
# Cover Letter Angle —— 一段自荐信定位建议, JD 定制版特色
# ================================================================

class CoverLetterAngle(_Base):
    """针对本 JD 的一段简短自荐信定位, 不写完整信件, 只给"开门 → 亮相 → 收尾"三段骨架。"""

    hook: str          # 开场如何切入 (一句)
    positioning: str   # 中段如何自我定位, 关联 JD 关键需求
    closing: str       # 收尾姿态 (行动而非乞求)


# ================================================================
# 面试预判 —— JD-specific, 与 career_resume 的通用 InterviewQuestion 分开命名
# ================================================================

class JDInterviewQuestion(_Base):
    """从 JD 与简历交叉推演出的高概率追问点。"""

    question: str
    #: 为什么会问 —— 必须能指到 JD 的哪一段或简历的哪一句
    why_it_will_be_asked: str
    #: 3-4 步回答框架 (强类型 list, 复用 career_resume 里那套 coerce)
    answer_framework: List[str] = Field(default_factory=list)
    #: 候选人应提前准备的具体事实
    facts_to_prepare: List[str] = Field(default_factory=list)
    avoid_saying: str = ""

    @field_validator("answer_framework", "facts_to_prepare", mode="before")
    @classmethod
    def _coerce_string_to_list(cls, v: Any) -> Any:
        # 与 career_resume.schema.InterviewQuestion 同款兜底: 防模板逐字符迭代爆版
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


# ================================================================
# 顶层报告
# ================================================================

class JDTargetedResumeReport(_Base):
    """JD 定制简历策略报告 · V1 schema."""

    meta: ReportMeta
    submit_decision: SubmitDecision

    #: JD 结构化解构 (Match Board 的行来源)
    jd_requirements: List[JDRequirement]
    #: 对齐总表
    match_board: MatchBoard
    #: 三段风险分层 (Phase 1 拆分) —— 各段严格按 requirement_type 分组
    must_have_blockers: List[MustHaveBlocker] = Field(default_factory=list)
    priority_gaps: List[PriorityGap] = Field(default_factory=list)
    inferred_risks: List[InferredRisk] = Field(default_factory=list)
    #: 值得凸显的 nice-to-have —— 简历上已有优势的放大机会
    strengths_to_amplify: List[str] = Field(default_factory=list)
    #: 落地文案卡
    rewrite_cards: List[RewriteCard]
    #: 投递前证据清单
    evidence_collection: EvidenceCollection
    #: 自荐信定位
    cover_letter_angle: CoverLetterAngle
    #: JD-specific 面试预判 (3-6 条)
    interview_preparation: List[JDInterviewQuestion] = Field(default_factory=list)

    #: 结语与合规文本 (privacy_and_scope_note 由服务端在渲染层覆盖为常量, 参见
    #: pipeline.build_render_context)
    final_words: str
    privacy_and_scope_note: str = ""

    # ---------------- 跨模型一致性 (真实性护栏) ----------------

    @model_validator(mode="after")
    def _check_ids_and_consistency(self) -> "JDTargetedResumeReport":
        # ============ 1. ID 唯一性 ============
        # jd_requirements[].id / rewrite_cards[].id / evidence_collection.items[].id
        # 全局唯一 —— 重复 id 会让下游"我改哪张卡"的引用彻底失效, 直接拒收。
        req_ids_list = [r.id for r in self.jd_requirements]
        card_ids_list = [c.id for c in self.rewrite_cards]
        ev_ids_list = [e.id for e in self.evidence_collection.items]

        def _dup_check(name: str, ids: List[str]) -> None:
            seen: Dict[str, int] = {}
            for i in ids:
                seen[i] = seen.get(i, 0) + 1
            dups = [k for k, v in seen.items() if v > 1]
            if dups:
                raise ValueError(f"{name} 出现重复 id: {dups}")

        _dup_check("jd_requirements[].id", req_ids_list)
        _dup_check("rewrite_cards[].id", card_ids_list)
        _dup_check("evidence_collection.items[].id", ev_ids_list)

        req_ids = set(req_ids_list)
        card_ids = set(card_ids_list)

        # ============ 2. Match Board 全量覆盖 ============
        # 每条 jd_requirement 必须**恰好**在 match_board 里对应一行, 不允许重复不允许漏。
        # 这是防止 LLM 在 board 里"挑着列"的关键校验。
        board_ids_list = [item.jd_requirement_id for item in self.match_board.items]
        _dup_check("match_board.items[].jd_requirement_id", board_ids_list)

        board_ids = set(board_ids_list)
        missing_in_board = req_ids - board_ids
        if missing_in_board:
            raise ValueError(
                f"以下 jd_requirement id 在 match_board.items 里没有对应行: "
                f"{sorted(missing_in_board)} —— 每条 JD 要求都必须在 Match Board 中出现。"
            )
        extra_in_board = board_ids - req_ids
        if extra_in_board:
            raise ValueError(
                f"match_board.items 出现了 jd_requirements 里不存在的 id: "
                f"{sorted(extra_in_board)}"
            )

        # ============ 3. requirement_type 冗余字段一致性 ============
        # match_board.items[].requirement_type 必须与其 jd_requirement_id 指向的
        # JDRequirement.requirement_type 完全一致 —— 出现分歧一定是 LLM 精神分裂
        # (同一条要求先说 must_have 后说 nice_to_have), 直接判无效。
        req_type_by_id = {r.id: r.requirement_type for r in self.jd_requirements}
        for item in self.match_board.items:
            expected = req_type_by_id[item.jd_requirement_id]
            if item.requirement_type != expected:
                raise ValueError(
                    f"MatchBoardItem(jd_requirement_id={item.jd_requirement_id!r}) 的 "
                    f"requirement_type={item.requirement_type!r} 与 jd_requirements 里声明的 "
                    f"{expected!r} 不一致; 同一条要求不能忽 must 忽 nice。"
                )

        # ============ 4. 三段风险分层各自锁死允许的 requirement_type ============
        status_by_req = {i.jd_requirement_id: i.status for i in self.match_board.items}
        broken_statuses = {"weakly_matched", "not_evidenced", "missing"}

        # 4a. must_have_blockers 必须指向 must_have, 且 status 不能是 matched
        for b in self.must_have_blockers:
            if b.jd_requirement_id not in req_ids:
                raise ValueError(
                    f"MustHaveBlocker.jd_requirement_id={b.jd_requirement_id!r} "
                    f"在 jd_requirements 里找不到。"
                )
            actual_type = req_type_by_id[b.jd_requirement_id]
            if actual_type != "must_have":
                raise ValueError(
                    f"MustHaveBlocker 只允许指向 requirement_type=must_have 的要求, "
                    f"但 {b.jd_requirement_id!r} 的类型是 {actual_type!r}; 请把这条移到 "
                    f"priority_gaps (preferred/nice_to_have) 或 inferred_risks (推断类)。"
                )
            status = status_by_req.get(b.jd_requirement_id)
            if status not in broken_statuses:
                raise ValueError(
                    f"MustHaveBlocker(jd_requirement_id={b.jd_requirement_id!r}) "
                    f"在 match_board 里的 status={status!r}, 说明这条其实已经 matched,"
                    f" 不应作为硬门槛风险; 请检查报告一致性。"
                )
            # blocker → rewrite → target 闭环强校验
            if b.linked_rewrite_card_id not in card_ids:
                raise ValueError(
                    f"MustHaveBlocker(jd_requirement_id={b.jd_requirement_id!r}) 的 "
                    f"linked_rewrite_card_id={b.linked_rewrite_card_id!r} 在 rewrite_cards "
                    f"里找不到; must_have_blockers 必须闭环到一张真实的改写卡。"
                )
            linked_card = next(c for c in self.rewrite_cards if c.id == b.linked_rewrite_card_id)
            if b.jd_requirement_id not in linked_card.targets_requirement_ids:
                raise ValueError(
                    f"MustHaveBlocker({b.jd_requirement_id!r}) 关联的改写卡 "
                    f"{linked_card.id!r} 的 targets_requirement_ids="
                    f"{linked_card.targets_requirement_ids!r} 里没有包含这条 requirement; "
                    f"blocker → rewrite → target 闭环断裂。"
                )

        # 4b. priority_gaps 只允许指向 preferred / nice_to_have
        for g in self.priority_gaps:
            if g.jd_requirement_id not in req_ids:
                raise ValueError(
                    f"PriorityGap.jd_requirement_id={g.jd_requirement_id!r} "
                    f"在 jd_requirements 里找不到。"
                )
            actual_type = req_type_by_id[g.jd_requirement_id]
            if actual_type not in ("preferred", "nice_to_have"):
                raise ValueError(
                    f"PriorityGap 只允许指向 requirement_type ∈ "
                    f"{{preferred, nice_to_have}} 的要求, 但 {g.jd_requirement_id!r} "
                    f"的类型是 {actual_type!r}; must_have 请入 must_have_blockers, "
                    f"inferred_from_context 请入 inferred_risks。"
                )
            if g.linked_rewrite_card_id and g.linked_rewrite_card_id not in card_ids:
                raise ValueError(
                    f"PriorityGap 引用了不存在的 rewrite_card_id="
                    f"{g.linked_rewrite_card_id!r}。"
                )

        # 4c. inferred_risks 只允许指向 inferred_from_context
        for ir in self.inferred_risks:
            if ir.jd_requirement_id not in req_ids:
                raise ValueError(
                    f"InferredRisk.jd_requirement_id={ir.jd_requirement_id!r} "
                    f"在 jd_requirements 里找不到。"
                )
            actual_type = req_type_by_id[ir.jd_requirement_id]
            if actual_type != "inferred_from_context":
                raise ValueError(
                    f"InferredRisk 只允许指向 requirement_type=inferred_from_context "
                    f"的要求, 但 {ir.jd_requirement_id!r} 的类型是 {actual_type!r}。"
                )
            if ir.linked_rewrite_card_id and ir.linked_rewrite_card_id not in card_ids:
                raise ValueError(
                    f"InferredRisk 引用了不存在的 rewrite_card_id="
                    f"{ir.linked_rewrite_card_id!r}。"
                )

        # ============ 5. Rewrite Card targets 必须都是真实 requirement ============
        for c in self.rewrite_cards:
            if not c.targets_requirement_ids:
                raise ValueError(
                    f"RewriteCard {c.id} 的 targets_requirement_ids 不能为空 —— "
                    f"每张改写卡至少要凸显一条 JD 要求。"
                )
            for rid in c.targets_requirement_ids:
                if rid not in req_ids:
                    raise ValueError(
                        f"RewriteCard {c.id} 的 targets_requirement_ids 包含未知 id={rid!r}"
                    )

        # ============ 6. Evidence 项的 linked ids 也要都真实存在 ============
        for e in self.evidence_collection.items:
            for rid in e.linked_requirement_ids:
                if rid not in req_ids:
                    raise ValueError(
                        f"EvidenceCollectionItem {e.id} linked_requirement_ids 包含未知 "
                        f"id={rid!r}"
                    )
            for cid in e.linked_rewrite_card_ids:
                if cid not in card_ids:
                    raise ValueError(
                        f"EvidenceCollectionItem {e.id} linked_rewrite_card_ids 包含未知 "
                        f"id={cid!r}"
                    )

        return self
