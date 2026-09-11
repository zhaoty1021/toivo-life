"""
HTML → PDF 的核心 orchestration。跨业务线复用。

外部只需要给:
  - render_context: dict, 塞进 Jinja2 环境的所有变量 (data, radar_svg, toc_pages, ...)
  - template_dir: 该业务线的模板目录 (含 report.html + report.css)
  - template_name: 模板文件名 (通常 "report.html")
  - output_pdf: 目标路径
  - allow_overflow: 是否绕过硬闸门

返回退出码 (0/2), 由 CLI 决定是否 exit(code)。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

from . import overflow_gate, toc
from .jinja_filters import register_all as register_filters
from .overflow_gate import EXIT_OK, EXIT_OVERFLOW, A4_HEIGHT_PX


def _inline_css(html: str, css_text: str, css_href: str) -> str:
    """把 <link rel="stylesheet" href="xxx.css"> 替换为 <style>...</style>"""
    return html.replace(
        f'<link rel="stylesheet" href="{css_href}">',
        f'<style>\n{css_text}\n</style>',
    )


def render_html_to_pdf(
    *,
    template_dir: Path,
    template_name: str,
    css_name: str,
    build_context: Callable[[Dict[str, int]], Dict[str, Any]],
    output_pdf: Path,
    debug_html_out: Optional[Path] = None,
    allow_overflow: bool = False,
    log=print,
) -> int:
    """
    build_context 是一个函数, 传入 toc_pages 字典, 返回渲染上下文。
    这样能支持两遍渲染: 第一遍传空 dict, 第二遍传真实页码。

    debug_html_out: 若给出, 把最终 HTML 写到这里, 方便浏览器手动排查。
    """
    env = Environment(loader=FileSystemLoader(str(template_dir)))
    register_filters(env)
    template = env.get_template(template_name)

    css_path = template_dir / css_name
    css_text = css_path.read_text(encoding="utf-8")

    output_pdf = Path(output_pdf)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)

    # pass 1 临时 HTML
    pass1_path = output_pdf.parent / (output_pdf.stem + ".pass1.html")
    pass1_html = _inline_css(template.render(**build_context({})), css_text, css_name)
    pass1_path.write_text(pass1_html, encoding="utf-8")

    exit_code = EXIT_OK

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 794, "height": A4_HEIGHT_PX})

        # ---------- pass 1: 测量目录页码 ----------
        page.goto(f"file://{pass1_path.resolve()}", wait_until="networkidle")
        toc_pages = toc.compute_toc_page_numbers(page)

        # ---------- pass 2: 用真实页码重渲染 ----------
        pass2_html = _inline_css(template.render(**build_context(toc_pages)), css_text, css_name)
        debug_out = debug_html_out or (output_pdf.parent / (output_pdf.stem + ".html"))
        debug_out.write_text(pass2_html, encoding="utf-8")
        page.goto(f"file://{debug_out.resolve()}", wait_until="networkidle")

        # ---------- 硬闸门 ----------
        all_pages, over = overflow_gate.measure_page_overflow(page)
        log(overflow_gate.format_overflow_report(all_pages, over))

        if over:
            if allow_overflow:
                log("  ⚠ --allow-overflow 已启用,强制继续生成 PDF。")
                log("    (强烈不建议在正式交付中使用此开关)")
            else:
                log("")
                log("  ✗ HARD GATE · 拒绝生成 PDF。")
                log("    修完溢出后重跑,或临时加 --allow-overflow 旁路 (仅调试用)。")
                log(f"    HTML 保留在: {debug_out}  可直接在浏览器打开定位问题元素。")
                exit_code = EXIT_OVERFLOW

        if exit_code == EXIT_OK:
            page.pdf(
                path=str(output_pdf),
                format="A4",
                print_background=True,
                margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
            )

        browser.close()

    try:
        pass1_path.unlink()
    except OSError:
        pass

    if exit_code == EXIT_OK:
        log(f"✓ PDF generated: {output_pdf}")
        log(f"  HTML preview: {debug_out}")
    else:
        if output_pdf.exists():
            log(f"  注意: 未覆盖现有 PDF {output_pdf} (它是上一次的产物,不是本次运行的结果)。")

    return exit_code
