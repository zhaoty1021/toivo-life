"""
Jinja2 filters + 图形生成器。

放在 render 层是因为它们跨业务线共享 —— JD 定制、项目梳理都会用 `hi` 高亮
`[待确认]`, 都可能画雷达图。

规则: 新增 filter 都要注册到 `register_all(env)` 里, 而不是让每个 pipeline
自己 env.filters[...] —— 保持共享层的唯一入口。
"""
from __future__ import annotations

import html as _html
import math
import re

from jinja2 import Environment
from markupsafe import Markup

_PLACEHOLDER_RE = re.compile(r"\[待确认:[^\[\]]*?\]")


def highlight_placeholders(text: str) -> Markup:
    """
    把 `[待确认: xxx]` 逐段替换为高亮 span。先 HTML 转义再正则替换,
    避免多次 replace 第一个 `]` 造成标签嵌套/未闭合。
    """
    if text is None:
        return Markup("")
    escaped = _html.escape(str(text))
    result = _PLACEHOLDER_RE.sub(
        lambda m: f'<span class="placeholder">{m.group(0)}</span>',
        escaped,
    )
    result = result.replace("\n", "<br>")
    return Markup(result)


def keep_newlines(text: str) -> Markup:
    """普通转义 + 保留换行, 不做占位符高亮"""
    if text is None:
        return Markup("")
    escaped = _html.escape(str(text)).replace("\n", "<br>")
    return Markup(escaped)


def build_radar_svg(radar: dict, size: int = 380) -> str:
    """手写 SVG 雷达图, 不依赖 pyecharts, 渲染更可控"""
    labels = list(radar.keys())
    values = list(radar.values())
    n = len(labels)
    cx = cy = size / 2
    max_r = size * 0.36
    rings = [0.25, 0.5, 0.75, 1.0]

    def polar(r, i):
        angle = -math.pi / 2 + 2 * math.pi * i / n
        return cx + r * math.cos(angle), cy + r * math.sin(angle)

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">']

    for ring in rings:
        pts = " ".join(f"{polar(max_r * ring, i)[0]:.1f},{polar(max_r * ring, i)[1]:.1f}" for i in range(n))
        parts.append(f'<polygon points="{pts}" fill="none" stroke="#d0d0d0" stroke-width="0.8" stroke-dasharray="3,3"/>')

    for i in range(n):
        x, y = polar(max_r, i)
        parts.append(f'<line x1="{cx}" y1="{cy}" x2="{x:.1f}" y2="{y:.1f}" stroke="#d0d0d0" stroke-width="0.8"/>')

    data_pts = " ".join(f"{polar(max_r * v / 100, i)[0]:.1f},{polar(max_r * v / 100, i)[1]:.1f}" for i, v in enumerate(values))
    parts.append(f'<polygon points="{data_pts}" fill="rgba(30,58,95,0.28)" stroke="#1e3a5f" stroke-width="2.2"/>')

    for i, v in enumerate(values):
        x, y = polar(max_r * v / 100, i)
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="#c9a961" stroke="#1e3a5f" stroke-width="1.5"/>')

    for i, label in enumerate(labels):
        x, y = polar(max_r + 26, i)
        anchor = "middle"
        if x < cx - 4:
            anchor = "end"
        elif x > cx + 4:
            anchor = "start"
        parts.append(f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" dominant-baseline="middle" font-size="12" font-family="PingFang SC,Microsoft YaHei,sans-serif" fill="#1a1a1a" font-weight="600">{label}</text>')
        vx, vy = polar(max_r + 26, i)
        parts.append(f'<text x="{vx:.1f}" y="{vy + 14:.1f}" text-anchor="{anchor}" font-size="10" font-family="Georgia,serif" fill="#c9a961" font-weight="700">{values[i]}</text>')

    parts.append('</svg>')
    return "".join(parts)


def register_all(env: Environment) -> None:
    """在 Jinja2 环境上一次性注册所有共享 filter"""
    env.filters["hi"] = highlight_placeholders
    env.filters["nl"] = keep_newlines
