"""
Provider registry。

上层通过 `get_provider(name)` 拿到实例, 不直接 import 具体类。
构造依赖(如 api_key)从 toivo.config 读取, 保证"环境变量只有一个入口"。
"""
from __future__ import annotations

from typing import Callable, Dict

from .base import LLMProvider, ProviderAuthError
from .. import config


def _build_anthropic() -> LLMProvider:
    from .anthropic_api import AnthropicAPIProvider
    key = config.get_anthropic_api_key()
    if not key:
        raise ProviderAuthError(
            "缺少 ANTHROPIC_API_KEY (可写到 .env 或环境变量)。"
            "若想在 Claude Code 里跑, 请改用 --provider claude_code + --from-json。"
        )
    return AnthropicAPIProvider(api_key=key, base_url=config.get_anthropic_base_url())


def _build_claude_code() -> LLMProvider:
    from .claude_code import ClaudeCodeProvider
    return ClaudeCodeProvider()


# name -> factory function; factory 才 import 实现, 避免装不必要的依赖
_REGISTRY: Dict[str, Callable[[], LLMProvider]] = {
    "anthropic": _build_anthropic,
    "claude_code": _build_claude_code,
}


def get_provider(name: str) -> LLMProvider:
    if name not in _REGISTRY:
        raise ValueError(f"未知 provider: {name!r}; 可选: {list(_REGISTRY)}")
    return _REGISTRY[name]()


def list_providers() -> list[str]:
    return list(_REGISTRY)
