"""
Product 抽象基类。

一条业务线 = 一个 Product 子类, 提供:
  1. name / version 元信息
  2. 从 product.yaml 里读取配置
  3. **input_model**: 业务专属的 Pydantic 输入模型 (每条业务自己声明"我要收哪些字段")
  4. build_prompts(inputs) → (system, user): inputs 是**已经通过 input_model 校验后的实例**
  5. parse_and_validate(raw_text) → 结构化对象 (通常是 Pydantic model)
  6. build_render_context(data, toc_pages) → 渲染上下文字典
  7. run(inputs, provider, output_pdf, ...): 全流程 orchestration (基类默认实现)

新业务线只要继承并覆盖 input_model + 3 个方法就够, 不用改 CLI / 不用改 render。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple, Type

import yaml
from pydantic import BaseModel

from ..render.html_to_pdf import render_html_to_pdf
from ..render.overflow_gate import EXIT_OK
from ..providers.base import LLMProvider


# 一个 Product 可接受的 LLM 输入入口方式。CLI 会用它做早期拒错, 让 "career_resume
# --inputs ..." 或 "jd_targeted_resume --input ..." 在读文件前就报错并给出正确用法,
# 不用等到 InputModel 因缺字段才失败。
#
# text : 单个纯文本文件 (CLI --input)。CLI 把文本装进产品业务字段字典。
# json : 结构化多字段 JSON 文件 (CLI --inputs)。CLI 加载后把 dict 原样传给产品。
INPUT_MODE_TEXT = "text"
INPUT_MODE_JSON = "json"


@dataclass
class ProductMeta:
    """product.yaml 的强类型化表示"""
    key: str                  # 业务线唯一标识, 例 "career_resume"
    display_name: str         # 面向用户的显示名
    version: str              # 语义版本
    prompt_file: str          # 相对于本业务线目录的 prompt 文本文件
    template_file: str        # 相对于本业务线 templates/ 的入口
    css_file: str             # 相对于本业务线 templates/ 的样式
    default_model: Optional[str] = None
    max_tokens: int = 8192
    temperature: float = 0.3
    notes: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)  # 供业务线自己塞额外字段


def load_product_meta(product_dir: Path) -> ProductMeta:
    yaml_path = product_dir / "product.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"缺少 {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    known = {
        "key", "display_name", "version", "prompt_file", "template_file", "css_file",
        "default_model", "max_tokens", "temperature", "notes",
    }
    extras = {k: v for k, v in raw.items() if k not in known}
    return ProductMeta(
        key=raw["key"],
        display_name=raw["display_name"],
        version=raw["version"],
        prompt_file=raw["prompt_file"],
        template_file=raw["template_file"],
        css_file=raw["css_file"],
        default_model=raw.get("default_model"),
        max_tokens=raw.get("max_tokens", 8192),
        temperature=raw.get("temperature", 0.3),
        notes=raw.get("notes", ""),
        extras=extras,
    )


class Product(ABC):
    """所有业务线基类"""

    #: 子类必须指向自己所在的目录 (含 product.yaml)
    product_dir: Path

    #: 子类必须指定自己的输入模型 (Pydantic BaseModel 子类)。
    #: 每条业务的输入结构不一样 —— 简历要 resume_text, 算命要 birth_datetime, 别硬套。
    input_model: Type[BaseModel]

    #: 该业务接受哪些 CLI 入口方式。用于 CLI 早期拒错 (在读文件、跑 LLM 前就报错)。
    #: 默认 {"text"} 兼容老业务; jd_targeted_resume 这种多材料业务应设为 {"json"}。
    accepted_input_modes: FrozenSet[str] = frozenset({INPUT_MODE_TEXT})

    def __init__(self):
        self.meta = load_product_meta(self.product_dir)

    # ---------------- 子类必须实现 ----------------

    @abstractmethod
    def build_prompts(self, inputs: BaseModel) -> Tuple[str, str]:
        """
        返回 (system, user)。

        inputs 是**已经通过 self.input_model.model_validate() 校验过**的实例,
        子类可以直接读它的字段, 不需要再做 dict.get / 类型校验。
        """
        raise NotImplementedError

    @abstractmethod
    def parse_and_validate(self, raw_text: str) -> Any:
        """
        解析 LLM 返回的原始文本 → 校验通过的结构化对象 (通常是 Pydantic model)。
        校验失败必须抛异常, 不许静默返回 None。
        """
        raise NotImplementedError

    @abstractmethod
    def build_render_context(self, data: Any, toc_pages: Dict[str, int]) -> Dict[str, Any]:
        """
        把结构化数据 + 目录页码字典 → 渲染上下文 dict, 直接传给 Jinja2。
        """
        raise NotImplementedError

    # ---------------- 基类默认 orchestration ----------------

    def run(
        self,
        *,
        inputs: Optional[Dict[str, Any]] = None,
        provider: Optional[LLMProvider] = None,
        provider_factory: Optional[Any] = None,
        from_json: Optional[Path] = None,
        output_pdf: Path,
        allow_overflow: bool = False,
        log=print,
    ) -> int:
        """
        运行整条流水线并返回退出码。

        - from_json 非空: 跳过 LLM, 直接用该 JSON 走渲染 (调试 / 已有诊断结果时用)
        - 否则: 先用 self.input_model.model_validate(inputs) 校验输入, **通过后**再拿 provider,
          最后调 LLM。这样"字段写错"能优先浮现, 不会被"缺 API key"覆盖。

        provider 传参两种方式二选一:
          - provider=<LLMProvider>       已经初始化好的实例, 老 CLI 兼容路径
          - provider_factory=<callable>  懒加载: 仅在 InputModel 校验通过后才调用它拿实例
        """
        if from_json is not None:
            import json as _json
            with open(from_json, encoding="utf-8") as f:
                raw_text = f.read()
            data = self.parse_and_validate(raw_text)
        else:
            if inputs is None:
                raise ValueError("走 LLM 时必须提供 inputs")
            # 关键: 输入侧严格校验, 打错字段名 / 少字段 / 类型错 → ValidationError, 不到 LLM
            validated = self.input_model.model_validate(inputs)
            # 校验通过后再拿 provider —— 不想让 "缺 API key" 掩盖 "字段写错"
            if provider is None:
                if provider_factory is None:
                    raise ValueError("走 LLM 时必须提供 provider 或 provider_factory")
                provider = provider_factory()
            system, user = self.build_prompts(validated)
            result = provider.complete(
                system=system,
                user=user,
                model=self.meta.default_model or provider.default_model(),
                max_tokens=self.meta.max_tokens,
                temperature=self.meta.temperature,
            )
            log(f"  · LLM: {result.model} · usage={result.usage}")
            data = self.parse_and_validate(result.text)

        # 渲染上下文函数: pass1 / pass2 会各调一次
        def build_context(toc_pages: Dict[str, int]) -> Dict[str, Any]:
            return self.build_render_context(data, toc_pages)

        template_dir = self.product_dir / "templates"
        return render_html_to_pdf(
            template_dir=template_dir,
            template_name=self.meta.template_file,
            css_name=self.meta.css_file,
            build_context=build_context,
            output_pdf=Path(output_pdf),
            allow_overflow=allow_overflow,
            log=log,
        )
