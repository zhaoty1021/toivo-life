"""
两遍渲染 + 目录页码计算。

放在共享 render 层是因为: JD 定制、项目梳理这些高端交付物大概率都会有目录页。
只要模板里放好 `data-toc-key="xxx"` 锚点, 就能拿到 {key: pageNo} 字典回传给模板。
"""
from __future__ import annotations

from typing import Dict


_TOC_JS = """
() => {
  const A4_H = document.querySelector('.page')
    ? document.querySelector('.page').clientHeight
    : 1123;
  const anchors = Array.from(document.querySelectorAll('[data-toc-key]'));
  return anchors.map(a => {
    const rect = a.getBoundingClientRect();
    const topAbs = rect.top + window.scrollY;
    const pageNo = Math.floor(topAbs / A4_H) + 1;
    return { key: a.getAttribute('data-toc-key'), pageNo };
  });
}
"""


def compute_toc_page_numbers(playwright_page) -> Dict[str, int]:
    """
    读取页面里所有 [data-toc-key] 的绝对 Y 偏移, 除以页高得到页码。
    """
    entries = playwright_page.evaluate(_TOC_JS)
    return {e["key"]: e["pageNo"] for e in entries}
