"""
Toivo 简历诊断 PDF 生成器

用法:
  python3 scripts/render.py --json <diagnosis.json> --output <name.pdf>
  python3 scripts/render.py ... --allow-overflow   # 紧急旁路,不建议

硬规则 (2026-09-11 起):
  只要检测到任一 .page 的内容高度超过 A4,PDF 不允许出货。
  这不是审计,这是闸门。因为每份 JSON 长度都不同,
  上一份不溢出不代表下一份不溢出——静默出货 = 交付事故。
"""
import json
import argparse
import math
import re
import sys
import html as _html
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup
from playwright.sync_api import sync_playwright

# 溢出闸门配置
OVERFLOW_TOLERANCE_PX = 2.0     # <=2px 视作亚像素舍入,不算溢出
A4_HEIGHT_PX = 1123             # A4 @ 96 dpi

# 退出码: 便于 CI/上游脚本区分失败原因
EXIT_OK = 0
EXIT_OVERFLOW = 2               # 溢出触发的硬闸
EXIT_OTHER = 1                  # 其他运行时错误 (由异常自然抛出)

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


# ------------ Jinja2 filters ------------
_PLACEHOLDER_RE = re.compile(r"\[待确认:[^\[\]]*?\]")


def highlight_placeholders(text: str) -> Markup:
    """
    把 `[待确认: xxx]` 逐段替换为高亮 span。
    先做 HTML 转义,再对已转义文本做正则匹配,
    避免多次替换第一个 `]` 导致的标签嵌套/未闭合问题。
    """
    if text is None:
        return Markup("")
    escaped = _html.escape(str(text))
    result = _PLACEHOLDER_RE.sub(
        lambda m: f'<span class="placeholder">{m.group(0)}</span>',
        escaped,
    )
    # 保留换行
    result = result.replace("\n", "<br>")
    return Markup(result)


def keep_newlines(text: str) -> Markup:
    """普通文本 + 保留换行,不做占位符高亮 (用于附录中兼容旧样式)。"""
    if text is None:
        return Markup("")
    escaped = _html.escape(str(text)).replace("\n", "<br>")
    return Markup(escaped)


def build_radar_svg(radar: dict, size: int = 380) -> str:
    """手写 SVG 雷达图,不依赖 pyecharts,渲染更可控"""
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


def measure_page_overflow(page, tolerance_px: float = 2.0):
    """
    在浏览器里检查每个 .page 是否有内容溢出。

    关键: .page 上有 `overflow: hidden` 作为视觉兜底,这会让 scrollHeight
    等于 clientHeight, 掩盖真实溢出。所以我们:
      1) 临时把所有 .page 的 overflow 改成 visible
      2) 用一个绝对定位的探针 div 逐个测量每个 .page 内子元素的
         最大 bottom (相对 .page 顶部) —— 这才是内容真正需要的高度
      3) 测完还原 overflow, 不影响 PDF 渲染

    返回 (all_pages_info, overflowing_pages)。
    """
    js = """
    () => {
      const pages = Array.from(document.querySelectorAll('.page'));
      // 备份并临时解除 overflow:hidden, 让 scrollHeight 反映真实内容高
      const originalOverflow = pages.map(p => p.style.overflow);
      pages.forEach(p => { p.style.overflow = 'visible'; });

      const results = pages.map((p, i) => {
        const clientH = p.clientHeight;
        const pageRect = p.getBoundingClientRect();

        // 1) 常规 scrollHeight (overflow:visible 下这次是真的)
        const scrollH = p.scrollHeight;

        // 2) 双保险: 找 .page 内所有后代元素中 bottom 最靠下的那个
        //    即使 flex/absolute 布局把子元素弹出容器, 这个也能抓到
        let maxBottom = 0;
        const descendants = p.querySelectorAll('*');
        for (const el of descendants) {
          const r = el.getBoundingClientRect();
          if (r.width === 0 && r.height === 0) continue;   // 跳过纯装饰空节点
          const bottomRel = r.bottom - pageRect.top;
          if (bottomRel > maxBottom) maxBottom = bottomRel;
        }

        // 取两种测量的较大值 —— 谁更大信谁
        const contentH = Math.max(scrollH, Math.ceil(maxBottom));
        const overflow = contentH - clientH;
        const label = p.getAttribute('data-chapter') || p.className;

        return {
          index: i + 1,
          label,
          scrollH,
          clientH,
          contentH,
          overflow,
        };
      });

      // 还原,不影响后续 PDF 打印
      pages.forEach((p, i) => { p.style.overflow = originalOverflow[i]; });

      return results;
    }
    """
    infos = page.evaluate(js)
    over = [p for p in infos if p["overflow"] > tolerance_px]
    return infos, over


def compute_toc(page):
    """
    读取页面上带 data-toc-key 的 anchor,返回 {key: page_number}。
    页码通过 anchor 的 boundingClientRect().top 与页高相除得到。
    """
    js = """
    () => {
      const A4_H = document.querySelector('.page') ? document.querySelector('.page').clientHeight : 1122;
      const anchors = Array.from(document.querySelectorAll('[data-toc-key]'));
      return anchors.map(a => {
        const rect = a.getBoundingClientRect();
        // 该 anchor 距文档顶部的绝对偏移
        const topAbs = rect.top + window.scrollY;
        const pageNo = Math.floor(topAbs / A4_H) + 1;
        return { key: a.getAttribute('data-toc-key'), pageNo };
      });
    }
    """
    entries = page.evaluate(js)
    return {e["key"]: e["pageNo"] for e in entries}


def render_pdf(json_path: str, output_pdf: str, allow_overflow: bool = False) -> int:
    """
    返回退出码:
      0 = 成功
      2 = 检测到溢出且未使用 --allow-overflow, PDF 未写出
    """
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    env.filters["hi"] = highlight_placeholders
    env.filters["nl"] = keep_newlines
    template = env.get_template("report.html")

    radar_svg = build_radar_svg(data["radar"])
    now = datetime.now()
    report_no = now.strftime("%Y%m%d%H%M")
    report_date = now.strftime("%Y.%m.%d")

    def render_with_toc(toc_pages: dict):
        return template.render(
            data=data,
            radar_svg=radar_svg,
            report_no=report_no,
            report_date=report_date,
            toc_pages=toc_pages,
        )

    # 第一遍渲染: 空 toc_pages, 让页面里的 anchor 就位以便测量
    html = render_with_toc({})

    css_path = TEMPLATES_DIR / "styles.css"
    css_text = css_path.read_text(encoding="utf-8")
    html = html.replace(
        '<link rel="stylesheet" href="styles.css">',
        f'<style>\n{css_text}\n</style>',
    )

    debug_html_pass1 = OUTPUT_DIR / (Path(output_pdf).stem + ".pass1.html")
    debug_html_pass1.write_text(html, encoding="utf-8")

    exit_code = EXIT_OK
    debug_html: Path | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 794, "height": A4_HEIGHT_PX})

        # ---------- Pass 1: 测量目录页码 ----------
        page.goto(f"file://{debug_html_pass1.resolve()}", wait_until="networkidle")
        toc_pages = compute_toc(page)

        # ---------- Pass 2: 用真实页码重渲染 ----------
        html2 = render_with_toc(toc_pages)
        html2 = html2.replace(
            '<link rel="stylesheet" href="styles.css">',
            f'<style>\n{css_text}\n</style>',
        )
        debug_html = OUTPUT_DIR / (Path(output_pdf).stem + ".html")
        debug_html.write_text(html2, encoding="utf-8")

        page.goto(f"file://{debug_html.resolve()}", wait_until="networkidle")

        # ---------- 溢出闸门 ----------
        infos, over = measure_page_overflow(page, tolerance_px=OVERFLOW_TOLERANCE_PX)
        print(f"  → 共 {len(infos)} 页")

        if over:
            print("  ✗ 检测到内容溢出的页面 (以下页面在 A4 高度下会被裁切):")
            print(f"    {'页码':>4}  {'章节标签':<20} {'溢出':>10}  相当于 A4 底部裁掉")
            print(f"    {'-'*4}  {'-'*20} {'-'*10}  {'-'*20}")
            for o in over:
                pct = o["overflow"] / A4_HEIGHT_PX * 100
                print(f"    {o['index']:>4}  {o['label']:<20} {o['overflow']:>7}px  约 {pct:>4.1f}%")

            print()
            if allow_overflow:
                print("  ⚠ --allow-overflow 已启用,强制继续生成 PDF。")
                print("    (强烈不建议在正式交付中使用此开关)")
                exit_code = EXIT_OK
            else:
                print("  ✗ HARD GATE · 拒绝生成 PDF。")
                print(f"    修完溢出后重跑,或临时加 --allow-overflow 旁路 (仅调试用)。")
                print(f"    HTML 保留在: {debug_html}  可直接在浏览器打开定位问题元素。")
                exit_code = EXIT_OVERFLOW
        else:
            print("  ✓ 所有页面高度符合 A4,无内容裁切")

        # 只有通过闸门才写 PDF
        if exit_code == EXIT_OK:
            page.pdf(
                path=output_pdf,
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )

        browser.close()

    # 清理 pass1 临时文件
    try:
        debug_html_pass1.unlink()
    except OSError:
        pass

    if exit_code == EXIT_OK:
        print(f"✓ PDF generated: {output_pdf}")
        if debug_html is not None:
            print(f"  HTML preview: {debug_html}")
    else:
        # 溢出闸门触发时,不要留下旧的 PDF 让人误以为是新的
        old_pdf = Path(output_pdf)
        if old_pdf.exists():
            print(f"  注意: 未覆盖现有 PDF {old_pdf} (它是上一次的产物,不是本次运行的结果)。")

    return exit_code


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--allow-overflow",
        action="store_true",
        help="紧急旁路: 即使检测到 A4 溢出也强制生成 PDF。仅调试/预览时使用,正式交付禁止。",
    )
    args = parser.parse_args()
    sys.exit(render_pdf(args.json, args.output, allow_overflow=args.allow_overflow))
