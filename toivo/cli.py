"""
Toivo CLI.

用法示例:

  # 走 Anthropic API 完整生成
  python -m toivo run career_resume --input resume.txt --output out.pdf

  # 跳过 LLM, 直接用已有诊断 JSON 只重跑渲染
  python -m toivo run career_resume --from-json output/zhaotianyu_diagnosis_v2.json --output out.pdf

  # 列出注册的业务线 / provider
  python -m toivo list-products
  python -m toivo list-providers

设计原则:
  - CLI 层不感知任何业务细节。所有诊断逻辑都在 products/<line>/ 里。
  - 环境变量只从 toivo.config 读; CLI 不直接 os.getenv。
  - 退出码遵循 render layer: 0=成功, 2=溢出阻断, 1=其他错误。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .products import get_product, list_products as _list_products
from .providers.registry import get_provider, list_providers as _list_providers
from .render.overflow_gate import EXIT_OK, EXIT_OVERFLOW, EXIT_OTHER


def _cmd_run(args) -> int:
    product = get_product(args.product)
    print(f"▶ 业务线: {product.meta.display_name} (v{product.meta.version})")

    output_pdf = Path(args.output)

    # 分两条路径: --from-json 跳过 LLM, 否则走 provider
    if args.from_json:
        from_json = Path(args.from_json)
        if not from_json.exists():
            print(f"✗ 找不到 JSON: {from_json}", file=sys.stderr)
            return EXIT_OTHER
        print(f"  · 跳过 LLM, 直接使用 {from_json}")
        return product.run(
            from_json=from_json,
            output_pdf=output_pdf,
            allow_overflow=args.allow_overflow,
        )

    if not args.input:
        print("✗ 走 LLM 时必须给 --input <简历文本文件>", file=sys.stderr)
        return EXIT_OTHER

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"✗ 找不到 input: {input_path}", file=sys.stderr)
        return EXIT_OTHER
    resume_text = input_path.read_text(encoding="utf-8")

    provider_name = args.provider or config.get_default_provider()
    print(f"  · Provider: {provider_name}")
    provider = get_provider(provider_name)

    # CLI 收 dict, 由 Product 用它自己的 InputModel 严格校验。
    # 这里不做字段选择性过滤 —— 少给的字段由 InputModel 的默认值兜; 多给的字段 InputModel
    # extra='forbid' 会直接报错, 这是我们想要的 (防止字段错拼默默丢字段)。
    inputs: dict = {"resume_text": resume_text}
    if args.target_role:
        inputs["target_role"] = args.target_role
    if args.target_company:
        inputs["target_company_or_industry"] = args.target_company
    if args.candidate_stage:
        inputs["candidate_stage"] = args.candidate_stage

    return product.run(
        inputs=inputs,
        provider=provider,
        output_pdf=output_pdf,
        allow_overflow=args.allow_overflow,
    )


def _cmd_list_products(args) -> int:
    for key in _list_products():
        p = get_product(key)
        print(f"  {key:20s}  v{p.meta.version:<6}  {p.meta.display_name}")
    return EXIT_OK


def _cmd_list_providers(args) -> int:
    for name in _list_providers():
        print(f"  {name}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="toivo", description="Toivo · 多业务线 AI 诊断工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="运行某条业务线的诊断流水线")
    run_p.add_argument("product", help="业务线 key (见 `list-products`)")
    run_p.add_argument("--input", help="输入文件 (走 LLM 时必须)")
    run_p.add_argument("--from-json", dest="from_json",
                       help="跳过 LLM, 直接从已有诊断 JSON 渲染")
    run_p.add_argument("--output", required=True, help="输出 PDF 路径")
    run_p.add_argument("--provider", choices=_list_providers(),
                       help="LLM provider (默认取 TOIVO_DEFAULT_PROVIDER, 通常 anthropic)")
    # 下面几个是简历业务用到的可选字段; 别的业务用不到就忽略 (InputModel extra='forbid' 会拦住)。
    # 之所以放在 CLI 而不是每个业务自建 argparse: 保持"一个 CLI 入口"约定;
    # 业务专属字段可以直接在这里加, 只在对应业务用得到, 别的业务默认收敛为 None 即可。
    run_p.add_argument("--target-role", dest="target_role",
                       help="career_resume: 候选人目标岗位方向")
    run_p.add_argument("--target-company", dest="target_company",
                       help="career_resume: 候选人目标公司或行业")
    run_p.add_argument("--candidate-stage", dest="candidate_stage",
                       help="career_resume: 候选人阶段 (校招/1-3 年/3-5 年/…)")
    run_p.add_argument("--allow-overflow", action="store_true",
                       help="旁路 A4 溢出硬闸门 (仅调试; 生产严禁使用)")
    run_p.set_defaults(func=_cmd_run)

    lp = sub.add_parser("list-products", help="列出所有已注册业务线")
    lp.set_defaults(func=_cmd_list_products)

    lpv = sub.add_parser("list-providers", help="列出所有已注册 LLM provider")
    lpv.set_defaults(func=_cmd_list_providers)

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyError as e:
        print(f"✗ {e}", file=sys.stderr)
        return EXIT_OTHER
    except Exception as e:
        # 让溢出闸门返回的 EXIT_OVERFLOW 走上面的 return 通道;
        # 其余异常在这里兜底,不吞栈 —— 打完之后返回 1。
        import traceback
        traceback.print_exc()
        return EXIT_OTHER


if __name__ == "__main__":
    sys.exit(main())
