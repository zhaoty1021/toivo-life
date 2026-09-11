"""
LLM Provider 抽象层

所有业务线走同一个接口: provider.complete(system, user, ...) -> str

添加新家:
  1. 在此目录建 xxx_api.py, 继承 LLMProvider, 实现 complete()
  2. 到 registry.py 里注册名字
  3. 上层无需改动

设计约束:
  - Provider 只负责"给我一段 prompt, 还我一段文本"; 不关心 JSON schema、模板、业务
  - Provider 不主动读环境变量, 由 config.py 传入; 便于测试和多账号切换
  - Provider 只抛两类异常: ProviderAuthError(4xx/key 无效) 和 ProviderRuntimeError(其他)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class ProviderError(Exception):
    """Provider 层通用错误基类"""


class ProviderAuthError(ProviderError):
    """密钥无效 / 权限不足 / 账户未激活等,重试也没用"""


class ProviderRuntimeError(ProviderError):
    """网络 / 超时 / 5xx / 模型端错误,重试可能有用"""


@dataclass
class CompletionResult:
    """
    一次 LLM 调用的返回值。
    text 是模型输出正文。usage 是可选的 token 用量, 用于成本审计和 A/B 对比。
    """
    text: str
    model: str
    usage: dict  # {"input_tokens": ..., "output_tokens": ...}, 若 provider 不返回则为空 dict
    raw: Optional[dict] = None  # 原始响应 (调试/审计用), 默认不带


class LLMProvider(ABC):
    """所有 LLM provider 的统一接口"""

    #: 供 registry / CLI 使用的短名字,子类必须覆盖 (例: "anthropic", "claude_code")
    name: str = "base"

    @abstractmethod
    def complete(
        self,
        *,
        system: str,
        user: str,
        model: Optional[str] = None,
        max_tokens: int = 8192,
        temperature: float = 0.3,
    ) -> CompletionResult:
        """
        单轮 completion。
        system + user 分离而不是拼在一起, 是因为 Anthropic API 就是这么分的,
        其他家(如 OpenAI)在 provider 内部再拼。上层不用管差异。
        """
        raise NotImplementedError

    def default_model(self) -> str:
        """provider 的默认模型 ID, 供 product.yaml 未指定时使用"""
        raise NotImplementedError
