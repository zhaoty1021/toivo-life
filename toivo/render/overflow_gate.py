"""
A4 溢出硬闸门。

关键设计:
  1. .page 上有 overflow:hidden 兜底 —— 视觉上不会翻出去, 但内容确实被裁。
     所以测量时必须临时把 overflow 切回 visible, 才能看到真实内容高。
  2. 双测量: scrollHeight + getBoundingClientRect().bottom 取大值,
     防止某些 flex/absolute 场景 scrollHeight 骗人。
  3. 默认硬阻断: 有溢出 → 不写 PDF → 返回 EXIT_OVERFLOW; 除非显式 allow_overflow。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple


A4_HEIGHT_PX = 1123  # A4 @ 96dpi
OVERFLOW_TOLERANCE_PX = 2.0

EXIT_OK = 0
EXIT_OVERFLOW = 2
EXIT_OTHER = 1


@dataclass
class PageInfo:
    index: int
    label: str
    scroll_h: int
    client_h: int
    content_h: int
    overflow: int


_MEASURE_JS = """
() => {
  const pages = Array.from(document.querySelectorAll('.page'));
  // 备份并临时解除 overflow:hidden, 让 scrollHeight 反映真实内容高
  const originalOverflow = pages.map(p => p.style.overflow);
  pages.forEach(p => { p.style.overflow = 'visible'; });

  const results = pages.map((p, i) => {
    const clientH = p.clientHeight;
    const pageRect = p.getBoundingClientRect();
    const scrollH = p.scrollHeight;

    // 双保险: 遍历所有后代, 取最靠下的 bottom
    let maxBottom = 0;
    const descendants = p.querySelectorAll('*');
    for (const el of descendants) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) continue;
      const bottomRel = r.bottom - pageRect.top;
      if (bottomRel > maxBottom) maxBottom = bottomRel;
    }

    const contentH = Math.max(scrollH, Math.ceil(maxBottom));
    const overflow = contentH - clientH;
    const label = p.getAttribute('data-chapter') || p.className;

    return { index: i + 1, label, scrollH, clientH, contentH, overflow };
  });

  // 还原, 不影响后续 page.pdf()
  pages.forEach((p, i) => { p.style.overflow = originalOverflow[i]; });
  return results;
}
"""


def measure_page_overflow(
    playwright_page, tolerance_px: float = OVERFLOW_TOLERANCE_PX
) -> Tuple[List[PageInfo], List[PageInfo]]:
    """
    返回 (all_pages, overflowing_pages)。
    """
    raw = playwright_page.evaluate(_MEASURE_JS)
    all_pages = [
        PageInfo(
            index=p["index"],
            label=p["label"],
            scroll_h=p["scrollH"],
            client_h=p["clientH"],
            content_h=p["contentH"],
            overflow=p["overflow"],
        )
        for p in raw
    ]
    over = [p for p in all_pages if p.overflow > tolerance_px]
    return all_pages, over


def format_overflow_report(all_pages: List[PageInfo], over: List[PageInfo]) -> str:
    """把测量结果打包成一段人类可读文本, 供 CLI 打印/日志记录"""
    lines = [f"  → 共 {len(all_pages)} 页"]
    if not over:
        lines.append("  ✓ 所有页面高度符合 A4,无内容裁切")
        return "\n".join(lines)

    lines.append("  ✗ 检测到内容溢出的页面 (以下页面在 A4 高度下会被裁切):")
    lines.append(f"    {'页码':>4}  {'章节标签':<20} {'溢出':>10}  相当于 A4 底部裁掉")
    lines.append(f"    {'-'*4}  {'-'*20} {'-'*10}  {'-'*20}")
    for o in over:
        pct = o.overflow / A4_HEIGHT_PX * 100
        lines.append(
            f"    {o.index:>4}  {o.label:<20} {o.overflow:>7}px  约 {pct:>4.1f}%"
        )
    return "\n".join(lines)
