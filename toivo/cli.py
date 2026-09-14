"""
Toivo CLI.

用法示例:

  # 单文本输入 (career_resume 用)
  python -m toivo run career_resume --input resume.txt --output out.pdf

  # 多材料 JSON 输入 (jd_targeted_resume 等多输入业务用)
  python -m toivo run jd_targeted_resume --inputs input/jd_case.json --output out.pdf

  # 跳过 LLM, 直接用已有诊断 JSON 只重跑渲染 (任何业务都行)
  python -m toivo run career_resume --from-json output/existing_report.json --output out.pdf

  # 列出注册的业务线 / provider
  python -m toivo list-products
  python -m toivo list-providers

设计原则:
  - CLI 层不感知任何业务细节。所有诊断逻辑都在 products/<line>/ 里。
  - 环境变量只从 toivo.config 读; CLI 不直接 os.getenv。
  - 退出码遵循 render layer: 0=成功, 2=溢出阻断, 1=其他错误。

三个入口的语义, 不要混:
  --input      单文本文件, CLI 会读文本 + 附加业务专属定位字段, 拼成 dict 传给 Product。
  --inputs     多字段 JSON 文件, CLI 只加载 JSON, 原样交给 Product 的 InputModel 校验。
  --from-json  已有 LLM 输出 JSON, 完全跳过 LLM, 只重渲染 PDF。

两层防线:
  第 1 层 (CLI): 按 product.accepted_input_modes 拒绝错误入口, 直接给业务可读的错误 + 正确命令。
  第 2 层 (InputModel, extra="forbid"): 拒绝字段名拼错 / 少字段 / 类型错。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

from . import config
from .products import get_product, list_products as _list_products
from .products.base import INPUT_MODE_JSON, INPUT_MODE_TEXT, Product
from .providers.registry import get_provider, list_providers as _list_providers
from .render.overflow_gate import EXIT_OK, EXIT_OVERFLOW, EXIT_OTHER


# ------------------------------- 输入入口辅助 --------------------------------


def _build_inputs_from_text(args, product: Product) -> Dict[str, Any]:
    """
    --input 路径: 读单文本 + 拼装业务专属定位字段。

    这些定位字段目前只对 career_resume 有意义; 别的业务如果不认这些字段, 会在 InputModel
    的 extra="forbid" 阶段被拒 —— 这是想要的行为, 说明业务用错了入口。
    """
    input_path = Path(args.input)
    if not input_path.exists():
        raise FileNotFoundError(f"找不到 input: {input_path}")
    resume_text = input_path.read_text(encoding="utf-8")

    inputs: Dict[str, Any] = {"resume_text": resume_text}
    if args.target_role:
        inputs["target_role"] = args.target_role
    if args.target_company:
        inputs["target_company_or_industry"] = args.target_company
    if args.candidate_stage:
        inputs["candidate_stage"] = args.candidate_stage
    return inputs


def _build_inputs_from_json(args, product: Product) -> Dict[str, Any]:
    """
    --inputs 路径: 读多字段 JSON, 原样交给 InputModel。

    CLI 不做 schema 感知; 字段对不对、多不多、少不少, 全部 InputModel 负责。
    """
    path = Path(args.inputs)
    if not path.exists():
        raise FileNotFoundError(f"找不到 inputs JSON: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"{path} 不是合法 JSON: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层必须是 JSON 对象 (dict), 得到 {type(data).__name__}")
    return data


def _reject_wrong_input_mode(product: Product, mode: str) -> str:
    """
    生成 CLI 层业务化的错误消息 (在 Product.run 之前抛)。
    返回给上层 print 到 stderr。
    """
    modes = ", ".join(sorted(product.accepted_input_modes))
    hints = []
    if INPUT_MODE_TEXT in product.accepted_input_modes:
        hints.append(f"  --input <resume.txt>            # 单文本文件")
    if INPUT_MODE_JSON in product.accepted_input_modes:
        hints.append(f"  --inputs <case.json>            # 多字段 JSON")
    hint_block = "\n".join(hints) if hints else "  (该业务未声明接受任何 LLM 输入方式)"
    return (
        f"✗ {product.meta.key} 不接受 --{'input' if mode == INPUT_MODE_TEXT else 'inputs'}。\n"
        f"  该业务接受的输入方式: {{{modes}}}\n"
        f"  请改用:\n{hint_block}"
    )


# ------------------------------- 子命令 --------------------------------


def _cmd_run(args) -> int:
    product = get_product(args.product)
    print(f"▶ 业务线: {product.meta.display_name} (v{product.meta.version})")

    output_pdf = Path(args.output)

    # 1. --from-json 一律走重渲染路径, 不管业务的 accepted_input_modes。
    if args.from_json:
        from_json = Path(args.from_json)
        if not from_json.exists():
            print(f"✗ 找不到 JSON: {from_json}", file=sys.stderr)
            return EXIT_OTHER
        # 明确性: 用户同时给了 --input/--inputs 又给了 --from-json, 说明认知混乱, 拦下来。
        if args.input or args.inputs:
            print(
                "✗ --from-json 已经跳过 LLM, 不要再传 --input / --inputs。\n"
                "  如果你是想让 LLM 重跑一次, 请去掉 --from-json。",
                file=sys.stderr,
            )
            return EXIT_OTHER
        print(f"  · 跳过 LLM, 直接使用 {from_json}")
        return product.run(
            from_json=from_json,
            output_pdf=output_pdf,
            allow_overflow=args.allow_overflow,
        )

    # 2. LLM 路径: --input / --inputs 必须二选一; 都给或都不给都是错。
    if args.input and args.inputs:
        print("✗ --input 与 --inputs 只能二选一 (前者单文本, 后者多字段 JSON)。", file=sys.stderr)
        return EXIT_OTHER
    if not args.input and not args.inputs:
        modes = ", ".join(sorted(product.accepted_input_modes))
        print(
            "✗ 走 LLM 时必须提供输入。该业务接受的方式: "
            f"{{{modes}}}。示例:\n"
            + ("  --input <resume.txt>\n" if INPUT_MODE_TEXT in product.accepted_input_modes else "")
            + ("  --inputs <case.json>\n" if INPUT_MODE_JSON in product.accepted_input_modes else ""),
            file=sys.stderr,
        )
        return EXIT_OTHER

    # 3. 按 accepted_input_modes 早拒错入口。业务化错误消息, 给具体正确用法。
    chosen_mode = INPUT_MODE_TEXT if args.input else INPUT_MODE_JSON
    if chosen_mode not in product.accepted_input_modes:
        print(_reject_wrong_input_mode(product, chosen_mode), file=sys.stderr)
        return EXIT_OTHER

    # 4. 按入口构造 dict。CLI 只搬运, 校验交给 InputModel。
    try:
        if chosen_mode == INPUT_MODE_TEXT:
            inputs = _build_inputs_from_text(args, product)
        else:
            inputs = _build_inputs_from_json(args, product)
    except (FileNotFoundError, ValueError) as e:
        print(f"✗ {e}", file=sys.stderr)
        return EXIT_OTHER

    provider_name = args.provider or config.get_default_provider()
    print(f"  · Provider: {provider_name} (校验通过后再加载)")

    return product.run(
        inputs=inputs,
        provider_factory=lambda: get_provider(provider_name),
        output_pdf=output_pdf,
        allow_overflow=args.allow_overflow,
    )


def _cmd_list_products(args) -> int:
    for key in _list_products():
        p = get_product(key)
        modes = ",".join(sorted(p.accepted_input_modes))
        print(f"  {key:22s}  v{p.meta.version:<6}  [{modes:9s}]  {p.meta.display_name}")
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

    # 三个入口互相独立解析, 语义靠 _cmd_run 里的校验闸门 (而不是 argparse 互斥组) 兜底。
    # argparse 层的 mutually_exclusive_group 报错难看, 也没法带业务上下文。
    run_p.add_argument("--input",
                       help="单文本输入文件 (只对接受 text 入口的业务; career_resume 用这个)")
    run_p.add_argument("--inputs",
                       help="多字段 JSON 输入文件 (只对接受 json 入口的业务; jd_targeted_resume 用这个)")
    run_p.add_argument("--from-json", dest="from_json",
                       help="跳过 LLM, 直接从已有诊断 JSON 渲染 (与 --input/--inputs 互斥)")

    run_p.add_argument("--output", required=True, help="输出 PDF 路径")
    run_p.add_argument("--provider", choices=_list_providers(),
                       help="LLM provider (默认取 TOIVO_DEFAULT_PROVIDER, 通常 anthropic)")

    # 下面几个是 career_resume 专属定位字段, 只在 --input 路径下用。别的业务如果需要
    # 传字段, 请走 --inputs JSON, 不要再给 CLI 加业务专属 flag。
    run_p.add_argument("--target-role", dest="target_role",
                       help="[career_resume · --input 专用] 候选人目标岗位方向")
    run_p.add_argument("--target-company", dest="target_company",
                       help="[career_resume · --input 专用] 候选人目标公司或行业")
    run_p.add_argument("--candidate-stage", dest="candidate_stage",
                       help="[career_resume · --input 专用] 候选人阶段 (校招/1-3 年/…)")

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
        # 其余异常在这里兜底, 不吞栈 —— 打完之后返回 1。
        import traceback
        traceback.print_exc()
        return EXIT_OTHER


if __name__ == "__main__":
    sys.exit(main())
