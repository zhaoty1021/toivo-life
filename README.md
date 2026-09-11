# Toivo

> 多业务线 AI 诊断工具。每条业务线只负责"这条业务怎么诊断", 底层的 LLM 调用、模板渲染、A4 溢出校验全部共享。

**当前上线业务线**

| Key | 名称 | 状态 |
|---|---|---|
| `career_resume` | Career · 简历深度诊断 · 通用版 (V2.2) | ✅ 正式 |
| `jd_targeted_resume` | JD 定制简历优化 | 🕓 规划中 |
| `project_deep_dive` | 项目深度梳理 | 🕓 规划中 |

---

## 一张图看懂: 业务如何独立, 入口/出口如何统一

```
                        ┌──────────────────────────────────────┐
     用户输入 (统一入口) │  python -m toivo run <业务线 key> ... │
                        └──────────────┬───────────────────────┘
                                       │
                              ┌────────▼────────┐
                              │  toivo.cli       │  单一 CLI, 只做参数解析
                              └────────┬────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │  toivo.products.<key>       │  业务线私有:
                        │    · product.yaml           │    · 用什么 prompt
                        │    · schema.py (Pydantic)   │    · 用什么模板
                        │    · pipeline.py            │    · 输出结构长什么样
                        │    · prompts/               │
                        │    · templates/             │
                        └──────┬───────────────┬──────┘
                               │               │
              ┌────────────────▼───┐     ┌─────▼────────────────┐
              │ toivo.providers    │     │ toivo.render         │
              │ 统一 LLM 出口       │     │ 统一渲染出口          │
              │  · anthropic       │     │  · html_to_pdf        │
              │  · claude_code     │     │  · overflow_gate      │
              │ 通过 toivo.config  │     │  · toc                │
              │ 读 API key         │     │  · jinja_filters      │
              └────────────────────┘     └───────┬───────────────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │  PDF (统一出口)          │
                                    │  · exit 0 = 成功         │
                                    │  · exit 2 = 溢出被阻断   │
                                    │  · exit 1 = 其他错误     │
                                    └─────────────────────────┘
```

**核心约束**
- 业务线之间**不互相 import**。想复用逻辑, 一律走 `toivo.render` / `toivo.providers`。
- 只有 `toivo.config` 允许 `os.getenv`, 其它模块要用环境变量必须从这里过。
- CLI 层不感知任何业务细节, 加新业务线不用改 CLI。

---

## 目录结构

```
toivo/                              # ← 项目根目录 (= 包名, 遵循 Python 标准布局)
├── toivo/                          # 主包 · 所有代码都在这里
│   ├── __main__.py                 #   `python -m toivo` 入口 (转发到 cli)
│   ├── cli.py                      #   ⬅ 统一入口: run / list-products / list-providers
│   ├── config.py                   #   ⬅ 统一环境变量出口 (唯一 os.getenv)
│   │
│   ├── products/                   # 【业务层】按业务线打包
│   │   ├── base.py                 #   Product ABC + product.yaml 加载
│   │   ├── __init__.py             #   业务线注册表 (key → Product 类)
│   │   └── career_resume/          #     · 简历深度诊断
│   │       ├── product.yaml        #       元信息 (prompt/模板/模型/温度)
│   │       ├── schema.py           #       Pydantic V2 校验模型
│   │       ├── pipeline.py         #       CareerResumeProduct(Product)
│   │       ├── prompts/            #       prompt 文本 (resume_v1/v2)
│   │       └── templates/          #       report.html + report.css
│   │
│   ├── providers/                  # 【能力层 · LLM】
│   │   ├── base.py                 #   LLMProvider ABC + CompletionResult
│   │   ├── anthropic_api.py        #   Anthropic 直连 (用户 API key)
│   │   ├── claude_code.py          #   Claude Code 会话模式 stub
│   │   └── registry.py             #   get_provider("anthropic" | "claude_code")
│   │
│   └── render/                     # 【能力层 · 渲染】
│       ├── html_to_pdf.py          #   pass1→测TOC→pass2→测溢出→出 PDF
│       ├── overflow_gate.py        #   A4 溢出硬闸门 (超一页就 exit=2)
│       ├── toc.py                  #   两遍渲染的目录页码测量
│       └── jinja_filters.py        #   共享 filter (hi/nl) + 雷达 SVG
│
├── input/                          # 简历原文 (纯文本)
├── output/                         # 生成产物 (JSON / HTML / PDF)
├── archive/v1_original/            # V1 原始代码归档, 只读, 不要 import
├── tests/                          # 单元测试
├── pyproject.toml                  # 包定义 + 依赖
├── .env.example                    # 环境变量模板
└── README.md                       # ← 本文件
```

### 一句话搞清楚各层职责

| 层 | 位置 | 只做一件事 |
|---|---|---|
| 入口 | `toivo/cli.py` | 解析命令行, 决定"跑哪条业务线, 用哪家 provider, 出到哪" |
| 业务 | `toivo/products/<key>/` | 定义这条业务线的 prompt / schema / 模板 / 上下文拼装 |
| LLM 出口 | `toivo/providers/` | 屏蔽 LLM 差异, 上层只关心 `complete(system, user) -> text` |
| 渲染出口 | `toivo/render/` | 屏蔽 HTML→PDF 复杂度, 上层只关心"给我上下文, 出 PDF" |
| 全局配置 | `toivo/config.py` | 全项目唯一读环境变量的地方 |

---

## 快速开始

### 1. 环境准备

```bash
pip install -e .
python -m playwright install chromium
cp .env.example .env      # 填入 ANTHROPIC_API_KEY (若走 Claude Code 可以不填)
```

### 2. 探路

```bash
python -m toivo list-products   # 看有哪些业务线
python -m toivo list-providers  # 看有哪些 LLM 出口
```

### 3. 全量运行 (自己的 Anthropic API key)

```bash
python -m toivo run career_resume \
  --input input/my_resume.txt \
  --output output/my_diagnosis.pdf
```

### 4. 只重跑渲染 (已经有 JSON, 只想调模板)

```bash
python -m toivo run career_resume \
  --from-json output/existing_diagnosis.json \
  --output output/re_render.pdf
```

### 5. 在 Claude Code 会话里跑

让 agent 自己走 prompt 并把结构化 JSON 落盘, 再用 `--from-json` 出 PDF。
(claude_code provider 目前是 stub, 会把 prompt 打到 stderr 提醒你手动执行。)

---

## 硬规则: A4 溢出闸门

每一页 (`<section class="page">`) 都会被 Playwright 测量。
只要有任何一页内容超过 A4 (1123px @ 96dpi 容差 2px):

- 打印溢出报告 (页码 · 章节标签 · 溢出多少 px · 相当于 A4 底部被裁多少 %)
- **不写 PDF · 进程退出码 2**
- HTML 保留在 `output/<name>.html` 供浏览器排查

这条规则是**默认开启**的, 因为 AI 输出长度会随简历不同而不同 —— 一份不溢出不代表下一份不会。
调试时可加 `--allow-overflow` 强制出货, **生产严禁使用**。

---

## 加一条新业务线

一条业务线 = `toivo/products/<key>/` 下一个独立的 Python 包, 实现 `Product` ABC 即可。**不要**从 `career_resume/` 复制 —— 那里包含大量简历领域假设 (雷达图、7 日计划、STAR 改写、`resume_text` 输入字段…), 复制会把这些假设当默认值带走。

### 一条业务线只欠 3 个东西

| 文件 | 作用 |
|---|---|
| `product.yaml` | 元信息: key / display_name / version / prompt_file / template_file / css_file / default_model / max_tokens / temperature / schema_class |
| `schema.py` | Pydantic V2 模型 — 严格定义这条业务的 LLM 输出结构。允许 `extra="allow"` 便于演进 |
| `pipeline.py` | 继承 `Product`, 覆盖三个方法: `build_prompts(inputs) -> (system, user)`、`parse_and_validate(raw_text) -> <你的模型>`、`build_render_context(data, toc_pages) -> dict` |

外加 `prompts/`, `templates/` 两个目录放素材, 以及一个 `InputModel` (Pydantic) 声明本业务需要哪些输入字段 —— 不要假设"所有业务都是一段文本"。

### 骨架

```
toivo/products/<new_key>/
├── product.yaml
├── schema.py            # 输出模型
├── pipeline.py          # class MyProduct(Product): ...
├── inputs.py            # 输入模型 (业务专属, 别复用简历那份)
├── prompts/main.txt
└── templates/report.html + report.css
```

### 6 步

1. 建目录结构 (上面那棵树)。
2. 写 `inputs.py` — 用 Pydantic 定义**这条业务需要什么输入**。做算命业务就是 `{ birth_datetime, gender }`, 别叫 `resume_text`。
3. 写 `product.yaml` — 元信息全填。`schema_class` 指向你的输出模型。
4. 写 `schema.py` — 从 prompt 输出规范倒推, 严格 `Literal` 化枚举, 别用裸 `str`。
5. 写 `pipeline.py` — 三个覆盖方法。`build_prompts` 里用 Jinja 或 `str.format_map` 把 InputModel 的字段填进 prompt 模板, 不要拼字符串。
6. 在 `toivo/products/__init__.py` 的 `_REGISTRY` 注册一行:
   ```python
   "<new_key>": lambda: __import__(
       "toivo.products.<new_key>.pipeline", fromlist=["MyProduct"]
   ).MyProduct(),
   ```

CLI / providers / 溢出闸门 / TOC 一行都不用改 —— 如果需要改, 说明公共层抽象漏了, 提回来讨论。

### 明确不要从 `career_resume` 继承的东西

- 输入字段命名 (`resume_text` 是简历特有)
- `mode: general | jd_targeted` (通用/JD 定制是两条独立业务, 不是一个 mode 开关)
- radar / seven_day_plan / STAR / interview_preparation 这些简历特有的输出结构
- `product.yaml` 里 `supported_modes` (业务自己决定要不要 mode 概念)

**可以复用的**只有: Product 生命周期、Provider 接口、溢出闸门、HTML→PDF 渲染、Jinja filters (通用的那些)、`toivo.config` 环境变量入口。

---

## 加一个新 LLM provider · 3 步

例如接入 OpenAI:

1. **写实现**: `toivo/providers/openai_api.py`, 继承 `LLMProvider`, 实现 `complete(...) -> CompletionResult`。
2. **加环境变量入口**: 在 `toivo/config.py` 里新增 `get_openai_api_key()`。
3. **注册工厂**: 在 `toivo/providers/registry.py` 的 `_REGISTRY` 加一行:
   ```python
   "openai": _build_openai,
   ```

CLI 会自动出现 `--provider openai` 选项。

---

## 常用命令速查

```bash
# 列表
python -m toivo list-products
python -m toivo list-providers

# 完整生成
python -m toivo run <product_key> \
  --input <resume.txt> \
  --output <out.pdf> \
  [--provider anthropic|claude_code] \
  [--target-role "岗位方向"] \
  [--target-company "公司/行业"] \
  [--candidate-stage "1-3 年"] \
  [--allow-overflow]     # 仅调试

# 从已有 JSON 只重渲染 (最常用)
python -m toivo run <product_key> \
  --from-json <existing.json> \
  --output <out.pdf>
```

**退出码**

| Code | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 内容溢出 A4, 已阻断, 未写 PDF |
| 1 | 其他错误 (校验失败 / provider 报错 / IO 异常等) |

---

## 环境变量 (只在 `.env` 里配)

| 变量 | 用途 | 谁用到 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 直连 Anthropic 的 key | `--provider anthropic` |
| `ANTHROPIC_BASE_URL` | 自建代理/中转 URL (可选) | 同上 |
| `TOIVO_DEFAULT_PROVIDER` | CLI 未显式 `--provider` 时的默认值 (默认 `anthropic`) | CLI |

**除了这三个变量, 项目里没有任何其它 `os.getenv`**。全部走 `toivo/config.py`。

---

## 开发原则

1. **业务分开, 入口/出口统一** — 业务线只知道自己那点事, 底层能力共享。
2. **数据驱动优先于代码** — 能放 `product.yaml` 的绝不 hard-code。
3. **失败必须显式** — LLM 输出错 → Pydantic ValidationError; 内容溢出 → exit=2。绝不静默降级。
4. **归档不删除** — V1 代码在 `archive/v1_original/`。想删磁盘时手动清即可, 主包不 import 归档目录。
