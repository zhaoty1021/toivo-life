"""
Claude Code provider stub。

当代码运行在 Claude Code 这类交互式 agent 里时, 不需要真正调用 API ——
你作为使用者已经在跟一个 Claude 模型对话了。此时的正确做法是:
把 (system + user) prompt 打印/写文件, 由外层 agent (即当前对话) 手工生成 JSON,
再走 --from-json 进入渲染管线。

它存在的意义是:
  1. 让 CLI 有一个明确的 "provider=claude_code" 选项, 而不是隐式假设
  2. 未来若 Claude Code 提供了 in-process 调用 API, 只改这个文件即可
"""
from __future__ import annotations

import sys
from typing import Optional

from .base import CompletionResult, LLMProvider, ProviderRuntimeError


class ClaudeCodeProvider(LLMProvider):
    name = "claude_code"

    # 在 Claude Code 环境里这个字段无实际意义, 但保留以满足接口
    DEFAULT_MODEL = "claude-code-host"

    def __init__(self):
        pass

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
        # 走到这里通常意味着调用方错用了: 在 Claude Code 里应该由 agent
        # 手工生成 JSON, 然后走 --from-json 进入渲染。
        # 打印明确的指引, 而不是抛神秘错误。
        print(
            "\n[claude_code provider] 此 provider 不主动调用 API。\n"
            "在 Claude Code 交互场景中, 请让 agent 手工产出符合 schema 的 JSON,\n"
            "然后用 `--from-json <path>` 跳过 LLM 直接进入渲染管线。\n"
            "\n下面是当前的 system + user prompt (可复制给对话使用):\n"
            "\n===== SYSTEM =====\n" + system +
            "\n===== USER =====\n" + user + "\n",
            file=sys.stderr,
        )
        raise ProviderRuntimeError(
            "claude_code provider 无法直接产出 completion。请用 --from-json 进入渲染, "
            "或用 --provider anthropic 走 API。"
        )
