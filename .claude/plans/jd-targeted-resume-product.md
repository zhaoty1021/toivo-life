# JD 定制简历诊断 · 高客单产品设计与落地计划

## 1. 产品定位

新增独立业务包 `jd_targeted_resume`，面向**技术岗求职者**，交付“针对一份具体 JD 的简历匹配诊断 + 可直接替换文案”。

它不是 `career_resume` 的 `mode`，两者的用户任务、判断依据和报告承诺完全不同：

| 项目 | `career_resume` | `jd_targeted_resume` |
|---|---|---|
| 用户问题 | 我的简历整体是否有说服力？ | 我的简历是否值得投这一个岗位，以及如何针对它修改？ |
| 判断基准 | 目标岗位方向的通用招聘画像 | 用户提交的具体 JD |
| 主要输入 | 简历 + 可选定位字段 | 简历 + JD 原文 + 目标岗位名称（可选补充公司名/候选人阶段） |
| 核心交付 | 通用竞争力诊断 | 要求—证据匹配矩阵、投递决策、定制改写包、面试风险预演 |
| 报告承诺 | 发现问题与通用改法 | 明确告诉用户：哪些经历能用于这份 JD、哪些不能硬蹭、哪些文字可直接替换 |

建议对外名称：**JD 定制简历策略报告**（英文副标：`JD-ALIGNED RESUME STRATEGY`）。

价格更高的依据不是页数，而是多了一层对具体岗位的“证据映射、取舍决策、定制文案和面试自证链”。报告必须让用户拿到后能按优先级直接修改，而不是收到一份泛泛的匹配分数。

## 1.1 开工前对齐的决策

### A. 不存 `match_score`

移除顶层的 `match_score` 与 `score_calibration`。JD 定制版不输出总分或百分比匹配度。

原因：具体 JD 的匹配并非线性可加总；一项关键硬门槛无证据，不能被多个普通关键词匹配“平均”；不同公司、团队和招聘阶段权重不同；伪精确分数会让用户把“材料未体现”误读为“能力低”。

报告保留以下决策字段：

```text
application_recommendation
executive_verdict
recommendation_rationale
must_have_blockers[]
```

`application_recommendation` 固定为：

```text
apply_now
revise_then_apply
do_not_target_now
```

Match Board 不由模型填写总分，也不让模型手工统计数量。Pipeline 基于 `requirement_evidence_matrix` 自动汇总以下状态：

```text
强证据                 strong_evidence
可补强                 partial_evidence
待候选人确认           needs_verification
当前材料未体现          not_evidenced
不建议硬蹭             do_not_claim
```

额外硬规则：任何 `must_have` 要求被标记为 `not_evidenced` 或 `do_not_claim` 时，报告必须明确说明它是否构成 `do_not_target_now` 的关键阻塞因素；不能被其他匹配项平均掉。

### B. 新增输入文件参数使用 `--inputs`

新增参数定为：

```bash
--inputs <path>
```

不使用 `--input-json` 或 `--params`：

- `--from-json` 已固定表示已有 LLM 输出，跳过生成、仅重渲染；
- `--inputs` 表示本次业务的原始输入材料集合，与未来 JSON/YAML/API 表单映射兼容；
- `--params` 容易被理解为运行参数或配置，而非简历、JD 等业务材料。

CLI 帮助必须明确：

```text
--inputs <path>
    业务输入 JSON 文件：传给该产品的 InputModel 后走 LLM 流程。
    与 --from-json 不同；后者是已有 LLM 输出，仅用于跳过生成并重渲染。
```

三个入口语义保持清晰：

```bash
# 单文本输入：适用于 career_resume
--input input/resume.txt

# 多字段、多材料输入：适用于 jd_targeted_resume
--inputs input/jd_case.json

# 已有报告 JSON：跳过 LLM，仅重渲染
--from-json output/existing_report.json
```

### C. CLI 层硬拒绝不支持的输入入口

不要等 InputModel 因缺少 `jd_text` 才失败。每个 Product 声明可接受的 LLM 输入方式：

```python
accepted_input_modes = frozenset({"text"})  # career_resume
accepted_input_modes = frozenset({"json"})  # jd_targeted_resume
```

CLI 在调用 `Product.run()` 前校验入口方式并给出业务可理解的错误。例：

```text
✗ jd_targeted_resume 不接受 --input。
  此业务需要“简历 + JD + 目标岗位”等结构化材料，请使用：

  --inputs input/jd_case.json

  文件示例：
  {
    "resume_text": "...",
    "jd_text": "...",
    "target_role": "Java 后端开发工程师"
  }
```

反向错误也要明确：`career_resume --inputs ...` 应提示该产品只接受 `--input <resume.txt>`。

CLI 判定顺序固定为：

```text
1. 有 --from-json：一律走重渲染路径。
2. 否则 --input 与 --inputs 必须二选一；同时给或都不给均报错。
3. 按 product.accepted_input_modes 校验入口；不支持时在 CLI 立即报错。
4. 读取文件并将 dict 传入 Product.run()。
5. InputModel 继续负责字段、类型、长度及 extra="forbid" 的严格校验。
```

即形成两层防线：CLI 负责入口方式正确，InputModel 负责业务字段正确。

### D. `evidence_collection_queue` 的正式结构

附录 B 的证据采集任务按“原经历”归组，而不是按 `rewrite_card_id` 重复罗列。每项结构如下：

```python
class EvidenceCollectionItem(_Base):
    collection_id: str
    priority: Literal["blocking", "high", "medium", "low"]

    source_experience: str
    source_resume_evidence: str

    facts_to_verify: list[str]
    recommended_verification_methods: list[str]

    why_it_matters: str
    related_requirement_ids: list[str]
    related_rewrite_card_ids: list[str]

    definition_of_done: str
```

优先级含义：

```text
blocking  不确认就无法判断是否该投或能否写入
high      确认后能显著提高 JD 匹配可信度
medium    可改善表达或补强次要要求
low       锦上添花
```

`definition_of_done` 必须将“去找数据”变成可核验的结束状态。例如：

```text
确认角色中心实际服务的业务线数量、典型权限场景、调用量级或可解释的替代业务规模，
并能在面试中说明数据来源。
```

PDF 中的呈现示例：

```text
阿里云 · 角色中心模块
├── [阻塞] 该模块实际服务什么业务、覆盖何种权限模型
├── [高] 是否有调用量、用户量或下游系统数量级
├── [高] 缓存、鉴权、关系建模的真实设计决策
├── 建议核实：项目文档 / 监控面板 / mentor / 历史 PR
└── 关联：Rewrite Card 02、Requirement R03、R07
```

### 已确认的默认实现判断

- Prompt 的正反例扩展为 5 组：已有 3 组外，补“关键词密度陷阱”和“隐性信号解读”。
- Prompt 静默自检与 Pydantic `model_validator` 共同构成真实性双闸门。
- 输出 Schema 顶层继续使用 `extra="allow"`；内层状态、优先级和放置位置使用 `Literal`。
- `product.yaml` 使用 `max_tokens: 16000`，`temperature: 0.3`。

## 2. 价值承诺与边界

### 必须交付

1. **JD 精读**：把 JD 从原始文本拆成岗位目标、核心职责、硬门槛、加分项、隐性信号、淘汰风险。
2. **证据匹配**：逐条对照 JD 与简历中的真实证据；明确区分“强证据 / 弱证据 / 未体现 / 待候选人确认 / 不建议硬蹭”。
3. **投递判断**：给出 `apply_now / revise_then_apply / do_not_target_now`，并说明这是“当前材料与该 JD 的匹配判断”，不是能力判决。
4. **简历定制策略**：确定首屏定位、经历排序、必须保留、应降级/删除、关键词与证据摆放位置。
5. **可直接替换文案**：产出 Summary、技能区、经历/项目 bullet 的 JD 定制版本；每条注明 `ready_to_use` 或 `needs_verification`。
6. **面试自证链**：将所有建议改写映射到可能被追问的问题与需要准备的事实，防止“为过筛而写进无法自证的内容”。
7. **最短执行路径**：给出投递前 60–90 分钟、半天、两天三个层级的修改清单。

### 不能承诺

- 不保证获得面试或 offer。
- 不把 JD 未提及的能力说成候选人不具备。
- 不因为 JD 出现关键词就建议候选人虚构经验。
- 不给没有简历证据支撑的量化数字、项目结果、工具使用经历。
- 不输出一份伪造的“完整重写简历”；第一版仅交付**各区块可直接替换文案包**，由用户在真实排版文件中替换。

## 3. 输入契约

新增 `toivo/products/jd_targeted_resume/inputs.py`，定义严格输入模型：

```python
class JDTargetedResumeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_text: str = Field(min_length=20)
    jd_text: str = Field(min_length=80)
    target_role: str = Field(min_length=2)
    target_company: str = ""
    candidate_stage: str = ""
```

第一版最小输入为 `resume_text + jd_text + target_role`。公司和阶段用于校准语气与岗位级别，但不作为必填门槛。

### CLI 输入方式

当前 CLI 只会读取一个 `--input`，无法满足多材料产品。为保持业务输入归属清晰，计划让 CLI 支持**通用 JSON 输入文件**：

```bash
python -m toivo run jd_targeted_resume \
  --inputs input/jd_case.json \
  --output output/jd_strategy.pdf
```

```json
{
  "resume_text": "...",
  "jd_text": "...",
  "target_role": "Java 后端开发工程师",
  "target_company": "某云厂商",
  "candidate_stage": "1-3 年"
}
```

同时保留现有 `career_resume --input <txt>` 的兼容路径。`--input` 与 `--inputs` 仅能二选一；`--from-json` 表示已有模型输出并优先进入重渲染路径。每个产品通过 `accepted_input_modes` 声明自己接受的入口，CLI 在读取并调用 `Product.run()` 前硬拒绝错误入口并展示相应的正确用法。CLI 不新增 `--jd`、`--resume-mode` 等业务专属开关；业务包的 `InputModel(extra="forbid")` 继续严格校验字段。

## 4. 报告结构（PDF）

目标长度：**约 20–28 页 A4**；每页必须是可独立阅读的结论页或操作页，不能为了“高价”堆砌重复文字。所有页面沿用现有 A4 溢出硬闸门与两遍目录页码计算。

### 封面与导航

| 页/章节 | 标题 | 用户得到什么 | 视觉重点 |
|---|---|---|---|
| 封面 | JD 定制简历策略报告 | 候选人、目标公司/岗位、报告编号、交付日期 | 深蓝 + 金色；`ONE ROLE · ONE STRATEGY` |
| 目录 | 本册路线图 | 每一章回答的问题 | 复用 TOC 能力，栏目改为 JD 对齐语义 |

### 核心决策层（先让用户知道该不该投）

| 章节 | 标题 | 必须内容 | 建议页数 |
|---|---|---|---|
| 01 | 这份岗位，值不值得用当前简历投 | 总体投递建议、无总分的 Match Board、最强三张牌、最高三项风险、投递前最低动作；明确 must-have 是否构成阻塞 | 1–2 页 |
| 02 | 我们到底在对齐什么岗位 | JD 一句话翻译、业务场景推断、岗位级别/角色定位、职责主线、硬门槛/加分项/隐性信号、JD 中应警惕的模糊要求 | 2 页 |
| 03 | 你的证据，和 JD 的要求逐条对上了吗 | 需求—证据矩阵：每项 JD 信号对应简历证据、证据强度、风险、建议动作 | 2–4 页 |

### 关键定制层（高价版的核心）

| 章节 | 标题 | 必须内容 | 建议页数 |
|---|---|---|---|
| 04 | 首屏应该让招聘方先看到什么 | 30 秒候选人画像、简历标题/个人简介建议、经历排序方案、应前置/降级/删除的内容、首屏检查清单 | 1–2 页 |
| 05 | JD 定制改写包 | 至少 5 条高价值改写；每条含 JD 对应要求、原文证据、改写策略、可直接替换文案、真实性状态、待确认信息、预计放置位置 | 5–7 页（每页 1 条） |
| 06 | 技能与关键词，不是都该往上加 | 对具体 JD 的关键词分层：必须显性体现、已有但弱、仅有真实经历才补、明确不建议硬蹭；附建议放置位置 | 2–3 页 |
| 07 | 投递前的版本控制清单 | “90 分钟快改 / 半天标准版 / 两天深改版”三种执行路径；每项有完成标准和对应收益 | 2 页 |

### 自证与转化层（让改写经得起追问）

| 章节 | 标题 | 必须内容 | 建议页数 |
|---|---|---|---|
| 08 | 写进简历后，面试官会怎么验证 | 4–6 个 JD 强相关追问：JD 信号、简历中的触发点、回答结构、事实准备清单、不能说的表达 | 2–3 页 |
| 附录 A | JD 信号全量拆解 | 未进入核心矩阵的次级要求、术语解释、为什么不应把某些词写进简历 | 1–2 页 |
| 附录 B | 待确认事实采集表 | 按经历整理需要向候选人/前同事/监控/文档核实的信息，作为后续人工沟通或二次优化输入 | 1–2 页 |
| 尾页 | 下一步 | 免责说明、二次校验/模拟面试/项目深挖等后续服务入口 | 1 页 |

### 核心视觉组件

不复用通用版的六维雷达图或 7 天计划。新增以下专属组件：

1. **JD 信号漏斗**：`硬门槛 → 核心职责 → 加分项 → 隐性信号`，呈现 JD 解析结果。
2. **Match Board（匹配看板）**：封面后第一张关键图，显示 `强匹配 / 可补强 / 待确认 / 无证据 / 不建议硬蹭` 的数量及决策结论。不要用“能力分”。
3. **需求—证据矩阵**：表格每行必须可追溯到 JD 原文和简历原文；避免只有关键词的机械匹配。
4. **30 秒首屏线框**：用简历区块排序而非复刻真实简历排版，强调“招聘方先看到什么”。
5. **Rewrite Card（定制改写卡）**：`JD 要求 → 现有证据 → 原文 → 推荐改写 → 可用状态 → 放置位置 → 面试追问`，一页一条以确保内容与 A4 可读性。
6. **真实性状态标识**：
   - `READY`：只基于现有简历事实，可直接使用；
   - `VERIFY`：需要补齐事实，文案中使用 `[待确认: ...]`；
   - `DO NOT CLAIM`：当前没有可信证据，不建议写入；
   - `REPOSITION`：不新增事实，仅调整已有经历的顺序与表达。

## 5. 输出 Schema 设计

新增 `schema.py`，输出侧继续采用 `extra="allow"` 以保障后续报告字段演进和旧 JSON 重渲染。所有状态字段使用 `Literal`；不使用自由文本枚举。

### 顶层建议结构

```text
JDTargetedResumeReport
├── 元信息：brand / product_line / product_name / series_no
├── 候选人与目标：candidate_name / candidate_stage / target_role / target_company
├── JD 摘要：jd_title / jd_source_summary / jd_scope_disclaimer
├── 投递决策：application_recommendation / executive_verdict / recommendation_rationale / must_have_blockers[]
├── Match Board：由 Pipeline 根据 requirement_evidence_matrix 自动汇总的状态计数
├── executive_summary
├── jd_intelligence
│   ├── role_mission
│   ├── business_context_inference
│   ├── seniority_and_scope
│   ├── must_have_requirements[]
│   ├── preferred_requirements[]
│   ├── hidden_signals[]
│   └── ambiguous_or_risky_signals[]
├── requirement_evidence_matrix[]
├── positioning_strategy
├── rewrite_pack[]
├── keyword_strategy[]
├── execution_paths
├── interview_validation[]
├── evidence_collection_queue[]
├── final_words / privacy_and_scope_note
```

### 关键模型与枚举

```python
ApplicationRecommendation = Literal[
    "apply_now", "revise_then_apply", "do_not_target_now"
]

EvidenceStatus = Literal[
    "strong_evidence", "partial_evidence", "needs_verification",
    "not_evidenced", "do_not_claim"
]

RequirementPriority = Literal["must_have", "core_responsibility", "preferred", "hidden_signal"]

RewriteType = Literal["ready_to_use", "needs_verification", "reposition_only", "do_not_claim"]

Placement = Literal[
    "headline", "professional_summary", "skills", "work_experience",
    "project_experience", "education", "academic_achievement", "other"
]
```

`RequirementEvidence` 的核心字段：

```text
requirement_id / jd_requirement / requirement_priority / why_it_matters
jd_evidence_quote / resume_evidence_quote / evidence_status
match_explanation / recommended_action / placement / interview_risk
```

`RewriteCard` 的核心字段：

```text
priority / title / targets_requirement_ids / placement / source_evidence
original_text / rewrite_strategy / rewrite_type / replacement_copy
facts_to_verify[] / evidence_needed / definition_of_done / interview_anchor
```

`EvidenceCollectionItem` 使用第 1.1 节定义的正式字段，并在 PDF 附录 B 按 `source_experience` 分组展示。

数据规则：

- `needs_verification` 的 `replacement_copy` 必须含 `[待确认: ...]`，且 `facts_to_verify` 非空。
- `ready_to_use` 不得引入简历未出现的具体数字、技术、公司范围或职责。
- `do_not_claim` 不输出替换文案，仅解释不能写入的原因和可替代的真实信号。
- 任一 `must_have` 的状态为 `not_evidenced` 或 `do_not_claim` 时，必须在 `must_have_blockers[]` 中明确是否构成投递阻塞；若仍建议投递，`recommendation_rationale` 必须给出基于 JD 原文和现有证据的例外理由。
- `match_board` 只由 Pipeline 从矩阵派生，不能作为模型自由生成或人工计数的字段。
- `requirement_evidence_matrix` 目标 12–20 条，至少覆盖全部 `must_have`。
- `rewrite_pack` 目标 5–8 条，至少 3 条有 `ready_to_use` 或可在补事实后直接使用的文案。
- `interview_validation` 目标 4–6 条，必须与报告中建议使用的文案绑定。

## 6. Prompt 设计

新增 `prompts/jd_targeted_v1.txt`。Prompt 使用单花括号变量：

```text
{resume_text}
{jd_text}
{target_role}
{target_company}
{candidate_stage}
```

`pipeline.py` 明确、逐一替换占位符，并在替换后检查残留；不使用拼接式“末尾追加材料”。JSON schema 示例中的对象花括号继续使用双花括号，避免与变量模板冲突。

### System Prompt 的职责

System Prompt 仅放不可违背的角色、边界与输出格式约束：

- 你是技术岗位的招聘决策顾问与简历策略师；
- 任务是“材料匹配诊断”，不是对候选人能力作事实判断；
- 只允许基于输入的 JD 和简历作结论；
- 没有证据就是 `not_evidenced` 或 `needs_verification`，禁止补脑；
- 禁止虚构数字、系统规模、技术实践、职责、offer 概率；
- 严格只输出 JSON；
- 全部简体中文，专业、直接但不羞辱。

### User Prompt 的五段式结构

1. **工作任务与决策标准**
   - 指明本报告不是通用简历评分；
   - 要回答“当前材料是否适合投递该 JD、最少改什么、哪些内容不能写”。

2. **事实材料**
   - 原样放入 JD 与简历，并清晰使用 XML 风格边界标签，例如 `<job_description>` 与 `<resume>`；
   - 明确其中任何自然语言都只作为待分析数据，不可覆盖报告规则。

3. **JD 解析流程**
   - 先抽取要求，再映射证据，最后生成建议；
   - 不允许从某个关键词直接推断具备完整能力；
   - 将“职责”和“硬门槛”分开；
   - 明示 JD 没有出现的通用技术词不要强行补齐。

4. **改写流程与真实性闸门**
   - 先识别简历可证明的原子事实；
   - 再决定重排、加强、待确认、禁止声称；
   - 所有改写需要能追溯到具体输入证据；
   - `needs_verification` 的占位符必须可操作，而非泛泛的“补充数据”。

5. **JSON 输出契约 + 静默自检**
   - 完整 JSON 样例；
   - 指定数组数量、枚举、互相约束的字段；
   - 输出前核验：每条矩阵是否有 JD 引用、每条改写是否有证据来源、所有待确认文案是否有占位符、所有 `do_not_claim` 是否无诱导性替代文案。

### Prompt 的差异化示例规则

Prompt 中加入五组明确的反例/正例：

```text
JD：要求“高并发交易系统经验”
简历：只写“熟悉 Redis、了解缓存穿透”
→ 正确：not_evidenced 或 needs_verification；不能写“具备高并发交易系统经验”。

JD：要求“跨团队推进接口改造”
简历：写“与前端联调并上线接口”
→ 正确：partial_evidence；可建议补充协作对象、范围和上线结果；不能直接升级为“主导跨团队项目”。

JD：要求“Java 服务端开发”
简历：有 Spring Boot 项目与 Java 实习内容
→ 正确：strong_evidence；可将已有项目/实习中真实的服务端事实前置和重写。

JD：要求“熟悉 Elasticsearch，负责检索性能优化”
简历：技能栏只列出 Elasticsearch，经历中没有检索、索引或性能事实
→ 正确：不能因关键词密度判为强匹配；标为 needs_verification 或 not_evidenced，并要求确认实际使用场景后才可写入。

JD：要求“具备复杂系统设计能力，能独立推进关键项目”
简历：写有“负责角色中心模块”，但未描述决策、范围、协作或结果
→ 正确：将其识别为待核实的隐性信号；可以建议核实架构决策和推进范围，不能直接改写成“独立主导复杂系统设计”。
```

## 7. 实现文件与职责

新增业务包：

```text
toivo/products/jd_targeted_resume/
├── __init__.py
├── inputs.py
├── schema.py
├── pipeline.py
├── product.yaml
├── prompts/
│   └── jd_targeted_v1.txt
└── templates/
    ├── report.html
    └── report.css
```

### 各文件责任

- `inputs.py`：仅定义 `JDTargetedResumeInput`，`extra="forbid"`。
- `schema.py`：定义报告输出、枚举与 Pydantic 跨字段规则；输出模型 `extra="allow"`。
- `pipeline.py`：读取/替换 Prompt；解析 JSON；组装 `data`、报告编号、日期、TOC 页码与必要的专属汇总数据。不要 import `career_resume`。
- `product.yaml`：`key: jd_targeted_resume`、独立名称/版本/Prompt/模板，`max_tokens: 16000`、`temperature: 0.3`。
- `report.html` / `report.css`：完全独立的 JD 视觉语言；可借鉴现有 A4 基础布局和 `hi` filter，但不复制雷达、7 天计划、通用版尾页文案。
- `toivo/products/__init__.py`：显式注册 `jd_targeted_resume`。

### 必要的公共层微调

当前 `cli.py` 把业务字段硬编码成简历通用版的 `resume_text` 与三个定位参数。这与新的多输入产品不兼容。

只做最小调整：增加 `--inputs <path>`，并规定：

- `--inputs` 时，加载 JSON object 并原样传给对应 `Product`；
- `--input` 与 `--inputs` 互斥，且在未使用 `--from-json` 时必须二选一；
- `--from-json` 仍优先于两种 LLM 输入方式；
- 每个产品声明 `accepted_input_modes`；CLI 在 Product.run 前拒绝不支持的入口，并输出产品对应的正确命令；
- `career_resume` 仅接受 `--input`，继续兼容其现有文本输入和三个定位字段；
- `jd_targeted_resume` 仅接受 `--inputs`，不把 `jd_text`、公司、岗位等特定字段继续硬编码成 CLI flags。

此处是新产品需要的唯一公共层修改，目标是让“每个产品自己的 InputModel”在真实多材料场景也能成立，同时让错误入口在 Pydantic 字段校验前获得可操作提示。

## 8. 验证与质量门槛

### 单元和语义回归

1. `JDTargetedResumeInput`：缺少 `jd_text`、短 JD、未知字段、错误字段名必须失败。
2. Prompt：所有 5 个占位符被替换；渲染后的 Prompt 不得残留变量占位符。
3. 输出 Schema：
   - 非法枚举失败；
   - `needs_verification` 没有占位符或待确认事实时失败；
   - `do_not_claim` 带替换文案时失败；
   - 老 JSON 带冗余字段可读取。
4. 产品注册：`python -m toivo list-products` 包含 `jd_targeted_resume`。

### 端到端回归

使用至少三类脱敏 fixture：

| Fixture | 目的 |
|---|---|
| 高匹配技术 JD | 验证强证据、可直接改写文案和 `apply_now/revise_then_apply` 逻辑 |
| 跨领域 JD | 验证不把相似关键词错判为能力，正确输出 `not_evidenced/do_not_claim` |
| 模糊/冗长 JD | 验证 JD 解析与报告分页稳定性 |

每个 fixture 验证：

- `--from-json` 可生成 HTML/PDF；
- 目录页码存在；
- 溢出页数为 0、退出码为 0；
- PDF 存在且大小超过合理阈值；
- Rendered HTML 包含每个主章节的 `data-toc-key`；
- 不用 PDF 二进制完全一致做回归判断（报告编号/日期可造成合理漂移）。

### 人工质量验收

从一份真实简历 + 真实技术 JD 抽查：

- 每一个“强匹配”都能在简历中找到原文；
- 每一项“JD 要求”都有来源；
- 所有可能提升候选人声明的文案都有 READY / VERIFY / DO NOT CLAIM 标识；
- 用户不看报告正文，仅按第 01、04、05、07 章也能在 90 分钟内完成一轮目标岗位定制；
- 报告不出现“把所有 JD 词塞满”的低质量策略。

## 9. 实施顺序

1. 新增 `--inputs` 的最小 CLI 通用多材料输入能力、`accepted_input_modes` 入口声明和互斥/早期拒绝校验，保持 `career_resume` 现有命令可用。
2. 建立 `jd_targeted_resume` 目录、注册表、产品配置和严格输入模型。
3. 先写输出 Schema 与跨字段约束，再写 Prompt，确保 Prompt/Schema 由同一份报告契约驱动。
4. 实现 pipeline 的占位符替换、JSON 解析和报告上下文。
5. 实现 PDF 模板：先封面/目录/匹配看板/矩阵/改写卡/行动路径/面试验证/尾页，再补附录。
6. 增加 fixture 和自动化回归，先用 `--from-json` 打磨模板与 A4 溢出，再接 LLM 全链路。
7. 用一份真实脱敏 case 做人工验收，迭代 Prompt 的证据引用与改写真实性约束。

## 10. 非目标（本期不做）

- 不输出完整 Word/LaTex 简历成品；
- 不解析 PDF/Docx，仍接收已提取的纯文本材料；
- 不做联网查询公司、岗位、面试题或薪资数据；
- 不做多轮用户追问会话；
- 不做模型编排、RAG、支付、账户、Web UI；
- 不把通用版模板、雷达图或七天计划抽成共享领域组件。
