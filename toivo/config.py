"""
全项目的环境变量入口。

规则:
  - 其他模块不许直接 os.getenv/os.environ。想读环境的东西, 都从这里过。
  - 支持 .env 文件 (可选依赖 python-dotenv, 装不装都不影响)。
  - 敏感值: 只在函数里返回, 不放模块级常量, 避免 import 时被日志/repr 意外打印。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_dotenv_loaded = False


def _load_dotenv_once():
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    try:
        from dotenv import load_dotenv  # type: ignore
        # 从项目根找 .env; 项目根 = 本文件的上上级
        root = Path(__file__).resolve().parent.parent
        env_path = root / ".env"
        if env_path.exists():
            load_dotenv(env_path)
    except ImportError:
        # 未装 dotenv 也不是错; 用户可以直接用 shell env
        pass
    _dotenv_loaded = True


def get_anthropic_api_key() -> Optional[str]:
    _load_dotenv_once()
    return os.getenv("ANTHROPIC_API_KEY") or None


def get_anthropic_base_url() -> Optional[str]:
    """允许自建/中转 URL, 一般不用"""
    _load_dotenv_once()
    return os.getenv("ANTHROPIC_BASE_URL") or None


def get_default_provider() -> str:
    """CLI 没显式 --provider 时用哪个 provider"""
    _load_dotenv_once()
    return os.getenv("TOIVO_DEFAULT_PROVIDER", "anthropic")
