"""
Anthropic 官方 API provider。
需要环境变量 ANTHROPIC_API_KEY (通过 config.py 传入, 不在此处直接读)。
"""
from __future__ import annotations

from typing import Optional

from .base import (
    CompletionResult,
    LLMProvider,
    ProviderAuthError,
    ProviderRuntimeError,
)


class AnthropicAPIProvider(LLMProvider):
    name = "anthropic"

    # 默认走当前家族最新可用的 Sonnet, 便宜且够用; product.yaml 里可覆盖为 opus。
    DEFAULT_MODEL = "claude-sonnet-5"

    def __init__(self, api_key: str, base_url: Optional[str] = None):
        if not api_key:
            raise ProviderAuthError("AnthropicAPIProvider 需要非空 api_key")
        try:
            import anthropic  # noqa: F401  延迟 import, 让"只用 claude_code 的用户"不必装依赖
        except ImportError as e:
            raise ProviderRuntimeError(
                "需要安装 anthropic 包: pip install anthropic"
            ) from e

        from anthropic import Anthropic
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = Anthropic(**kwargs)

    def default_model(self) -> str:
        return self.DEFAULT_MODEL

    def complete(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> CompletionResult:
        model_id = model or self.DEFAULT_MODEL
        try:
            resp = self._client.messages.create(
                model=model_id,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            # anthropic sdk 的异常层级依版本变化; 用字符串启发式分开鉴权错误
            msg = str(e).lower()
            if any(k in msg for k in ("api key", "unauthorized", "authentication", "permission")):
                raise ProviderAuthError(str(e)) from e
            raise ProviderRuntimeError(str(e)) from e

        # 拼所有 text block 的内容
        text_parts = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
        text = "".join(text_parts)

        usage = {}
        if getattr(resp, "usage", None):
            usage = {
                "input_tokens": getattr(resp.usage, "input_tokens", 0),
                "output_tokens": getattr(resp.usage, "output_tokens", 0),
            }

        return CompletionResult(text=text, model=model_id, usage=usage)
