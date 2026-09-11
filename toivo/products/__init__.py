"""
业务线注册表 (products registry)。

只在这里维护 key → Product 类的映射, CLI / pipeline / 测试都从这里取,
其它地方一律不许硬编码 "career_resume" 字符串以外的实例化路径。

新增业务线的时候: 建目录 + 写子类 + 在这里加一行 → 完事。
"""
from __future__ import annotations

from typing import Callable, Dict, List

from .base import Product


def _load_career_resume() -> Product:
    from .career_resume import CareerResumeProduct
    return CareerResumeProduct()


_REGISTRY: Dict[str, Callable[[], Product]] = {
    "career_resume": _load_career_resume,
    # 预留:
    # "jd_targeted_resume": lambda: __import__(...).JDTargetedResumeProduct(),
    # "project_deep_dive":  lambda: __import__(...).ProjectDeepDiveProduct(),
}


def get_product(key: str) -> Product:
    if key not in _REGISTRY:
        raise KeyError(
            f"未知业务线 {key!r}。已注册: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[key]()


def list_products() -> List[str]:
    return sorted(_REGISTRY)
