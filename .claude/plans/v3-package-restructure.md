# V3 包结构重构 · toivo 单仓多业务线

## Goal
把当前只支持一条业务线(Career 简历诊断)的紧耦合脚本,重构为可容纳多条业务线的 Python 包结构。要点:
- 统一的 LLM 出口(provider 层):现在两家(Anthropic API + Claude Code),将来加家不改上层代码
- 每条业务线独立目录 + product.yaml 元信息驱动:新增业务线拷 YAML 改字段,不改渲染/CLI
- 输出 JSON 用 Pydantic 校验:LLM 返回后即刻验、字段错位当场报错
- 渲染 / 溢出闸门 / 目录页码计算 = 跨业务线共享层
- 现有赵天宇 case 必须原样跑通,PDF 结构不变、溢出闸门仍生效

## 目录结构

```
toivo/
├── pyproject.toml
├── .env.example
├── README.md
├── toivo/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py                    # 唯一环境变量入口
│   ├── providers/
│   │   ├── __init__.py
│   │   ├── base.py                  # LLMProvider 抽象
│   │   ├── anthropic_api.py         # ANTHROPIC_API_KEY 走官方
│   │   ├── claude_code.py           # 在 Claude Code 里跑时的 stub
│   │   └── registry.py
│   ├── products/
│   │   ├── __init__.py
│   │   ├── base.py                  # Product 抽象
│   │   └── career_resume/
│   │       ├── __init__.py
│   │       ├── product.yaml
│   │       ├── schema.py            # Pydantic V2 schema
│   │       ├── pipeline.py          # 简历文本 → LLM → JSON → PDF
│   │       ├── prompts/
│   │       │   ├── v1.txt
│   │       │   └── v2.txt
│   │       └── templates/
│   │           ├── report.html
│   │           └── report.css
│   ├── render/
│   │   ├── __init__.py
│   │   ├── html_to_pdf.py
│   │   ├── overflow_gate.py
│   │   ├── toc.py
│   │   └── jinja_filters.py
│   └── shared/
│       ├── fonts/                   # 从 static/fonts/ 挪
│       └── css/                     # 先留空,以后拆共享 tokens
├── tests/
│   ├── fixtures/
│   │   └── zhaotianyu_v2.json
│   ├── test_overflow_gate.py
│   └── test_schema.py
├── output/                          # 保持,gitignore
└── archive/
    └── v1_original/                 # 老的 scripts/prompts/templates 挪这儿
```

## 迁移步骤

1. **创建 toivo 包骨架**:所有 `__init__.py` + 空目录
2. **provider 层**:base 抽象 + anthropic_api 实现 + claude_code stub + registry
3. **render 层**:把 scripts/render.py 里非业务的部分拆出来
   - `html_to_pdf.py`:Playwright 相关
   - `overflow_gate.py`:硬闸门 + 探针 JS
   - `toc.py`:两遍渲染 + 目录页码计算
   - `jinja_filters.py`:hi / nl / build_radar_svg
4. **career_resume 业务线**:
   - `product.yaml`:声明它用哪个 prompt / 哪个模板 / 哪个 schema / 默认 provider
   - `schema.py`:把 prompts/resume_v2.txt 里的 JSON 结构翻成 Pydantic
   - `pipeline.py`:orchestrate prompt fill → provider call → schema validate → render
   - 迁移 prompts/*.txt、templates/*.{html,css}
5. **CLI**:`python -m toivo run career_resume --input resume.txt --output x.pdf`,支持 `--provider claude_code|anthropic`,支持 `--from-json` 跳过 LLM
6. **回归**:用现有 `output/zhaotianyu_diagnosis_v2.json` 走 `--from-json` 跑一遍,新 PDF 与旧 PDF 视觉一致、溢出闸门仍工作、200x stress 仍拦下
7. **归档**:老 `scripts/` `prompts/` `templates/` `static/` 移入 `archive/v1_original/`

## 验证

- [ ] `python -m toivo run career_resume --from-json output/zhaotianyu_diagnosis_v2.json --output tmp.pdf` 成功
- [ ] `python -m toivo run career_resume --from-json <200x stress fixture> --output tmp.pdf` 退出码 2、无 PDF
- [ ] `python -m toivo list-products` 列出 career_resume
- [ ] `python -m toivo run career_resume --provider anthropic --resume input/xxx.txt` 走 Anthropic API 生成 JSON 再渲染(需 ANTHROPIC_API_KEY)
- [ ] Pydantic 校验:故意把 `overall_score` 改成字符串,应当场报错

## 不做

- OpenAI/Gemini provider 只留占位,不写代码
- shared/css/ 只建目录,不做跨业务线 CSS 抽取(以后加 JD 定制时再拆)
- pyproject.toml 只声明依赖,不发包
- tests/ 只做闸门 + schema 两个关键回归,不追求全覆盖
