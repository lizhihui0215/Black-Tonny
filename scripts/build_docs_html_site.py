#!/usr/bin/env python3
"""Generate a static HTML manuals site from markdown files under docs/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import html
import os
import re
import shutil

import markdown


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
OUTPUT_DIR = DOCS_DIR / "manuals"

DOC_CATEGORY_ORDER = [
    "总导航",
    "内容增长线",
    "店铺经营基础",
    "小团队管理线",
    "引流与成交",
    "库存与进货",
    "会员与扩品",
    "看板与数据",
    "Pages 与发布",
    "仪表盘输出",
]

SKIP_PARTS = {"manuals"}
SKIP_NAMES = {".nojekyll"}

CSS = """
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  color: #0f172a;
  background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
}
.page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px 48px;
}
.hero {
  background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 100%);
  color: #fff;
  border-radius: 24px;
  padding: 28px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.18);
}
.hero h1 {
  margin: 0 0 10px;
  font-size: 34px;
  line-height: 1.2;
}
.hero p {
  margin: 0;
  font-size: 15px;
  line-height: 1.8;
  opacity: 0.94;
}
.hero-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 18px;
}
.hero-actions a,
.small-link,
.nav-chip {
  text-decoration: none;
}
.hero-actions a {
  border-radius: 999px;
  padding: 12px 18px;
  font-size: 14px;
  font-weight: 700;
}
.btn-primary {
  background: #f8fafc;
  color: #0f172a;
}
.btn-secondary {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.22);
}
.top-nav {
  position: sticky;
  top: 0;
  z-index: 50;
  margin-bottom: 18px;
  background: rgba(248, 250, 252, 0.92);
  backdrop-filter: blur(14px);
  border: 1px solid rgba(148, 163, 184, 0.18);
  border-radius: 18px;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
}
.top-nav-links {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  padding: 12px;
}
.top-nav-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  padding: 9px 14px;
  font-size: 13px;
  font-weight: 800;
  color: #334155;
  background: #ffffff;
  border: 1px solid #dbe4f0;
  text-decoration: none;
}
.top-nav-link.is-active {
  background: #dbeafe;
  color: #1d4ed8;
  border-color: #bfdbfe;
}
.breadcrumbs,
.meta-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 14px 0 0;
}
.nav-chip,
.meta-chip {
  display: inline-flex;
  align-items: center;
  border-radius: 999px;
  padding: 7px 12px;
  font-size: 12px;
  font-weight: 700;
}
.nav-chip {
  background: rgba(255, 255, 255, 0.14);
  color: #fff;
  border: 1px solid rgba(255, 255, 255, 0.18);
}
.meta-chip {
  background: #eff6ff;
  color: #1d4ed8;
}
.section {
  margin-top: 22px;
  background: #fff;
  border-radius: 20px;
  padding: 20px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}
.section h2 {
  margin: 0 0 8px;
  font-size: 22px;
}
.section-note {
  margin: 0;
  font-size: 14px;
  line-height: 1.8;
  color: #475569;
}
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  margin-top: 16px;
}
.page-shell {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 18px;
  margin-top: 22px;
}
.main-column {
  min-width: 0;
}
.side-rail {
  display: flex;
  flex-direction: column;
  gap: 16px;
  align-self: start;
}
.rail-panel {
  position: sticky;
  top: 88px;
  background: #fff;
  border-radius: 20px;
  padding: 18px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}
.rail-panel h2 {
  margin: 0 0 8px;
  font-size: 18px;
}
.rail-panel p {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.8;
  color: #475569;
}
.rail-links {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.rail-links a {
  display: block;
  text-decoration: none;
  color: #334155;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 10px 12px;
  font-size: 13px;
  font-weight: 700;
}
.rail-links a.current {
  background: #dbeafe;
  border-color: #bfdbfe;
  color: #1d4ed8;
}
.card {
  border: 1px solid #e2e8f0;
  border-radius: 18px;
  padding: 16px;
  background: #fff;
}
.card-kicker {
  font-size: 12px;
  font-weight: 800;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}
.card h3 {
  margin: 0 0 8px;
  font-size: 18px;
}
.card p {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.8;
  color: #475569;
}
.card a {
  color: #1d4ed8;
  font-size: 13px;
  font-weight: 700;
}
.doc-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 18px;
}
.doc-article {
  background: #fff;
  border-radius: 20px;
  padding: 24px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}
.doc-article h1,
.doc-article h2,
.doc-article h3,
.doc-article h4 {
  color: #0f172a;
  line-height: 1.4;
}
.doc-article h1 {
  font-size: 34px;
  margin-top: 0;
}
.doc-article h2 {
  font-size: 24px;
  margin-top: 28px;
}
.doc-article h3 {
  font-size: 20px;
  margin-top: 24px;
}
.doc-article p,
.doc-article li {
  font-size: 15px;
  line-height: 1.9;
  color: #334155;
}
.doc-article a {
  color: #1d4ed8;
}
.doc-article table {
  width: 100%;
  border-collapse: collapse;
  margin: 16px 0;
  display: block;
  overflow-x: auto;
}
.doc-article th,
.doc-article td {
  border: 1px solid #dbe4f0;
  padding: 10px 12px;
  text-align: left;
  font-size: 14px;
  white-space: nowrap;
}
.doc-article th {
  background: #f8fafc;
}
.doc-article pre {
  background: #0f172a;
  color: #e2e8f0;
  padding: 14px;
  border-radius: 14px;
  overflow-x: auto;
}
.doc-article code {
  font-family: "SFMono-Regular", SFMono-Regular, Consolas, monospace;
  font-size: 0.95em;
}
.doc-article blockquote {
  border-left: 4px solid #93c5fd;
  margin: 18px 0;
  padding: 6px 0 6px 14px;
  color: #475569;
  background: #f8fbff;
}
.toc-panel {
  position: sticky;
  top: 18px;
  align-self: start;
  background: #fff;
  border-radius: 20px;
  padding: 18px;
  box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);
}
.toc-panel h2 {
  margin: 0 0 10px;
  font-size: 18px;
}
.toc-panel p {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.8;
  color: #475569;
}
.toc-panel .toc {
  font-size: 14px;
  line-height: 1.8;
}
.toc-panel ul {
  margin: 0 0 0 18px;
  padding: 0;
}
.doc-footer {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 20px;
}
.footer-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 14px;
}
.footer-card .label {
  font-size: 12px;
  text-transform: uppercase;
  color: #64748b;
  font-weight: 800;
  margin-bottom: 6px;
}
.footer-card a {
  color: #1d4ed8;
  text-decoration: none;
  font-size: 14px;
  font-weight: 700;
}
.footer-card p {
  margin: 8px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.7;
}
.footer-note {
  margin-top: 18px;
  font-size: 12px;
  line-height: 1.8;
  color: #64748b;
}
@media (max-width: 880px) {
  .page-shell,
  .doc-layout {
    grid-template-columns: 1fr;
  }
  .side-rail,
  .toc-panel,
  .rail-panel {
    position: static;
  }
  .rail-links {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (max-width: 640px) {
  .page {
    padding: 14px 12px 28px;
  }
  .hero {
    padding: 20px;
    border-radius: 18px;
  }
  .hero h1 {
    font-size: 26px;
  }
  .hero p,
  .section-note,
  .doc-article p,
  .doc-article li {
    font-size: 14px;
  }
  .top-nav-links,
  .hero-actions a {
    width: 100%;
    text-align: center;
    box-sizing: border-box;
  }
  .top-nav-link {
    width: 100%;
    text-align: center;
    box-sizing: border-box;
  }
  .section,
  .doc-article,
  .toc-panel,
  .rail-panel {
    padding: 16px;
    border-radius: 16px;
  }
  .rail-links {
    grid-template-columns: 1fr;
  }
  .doc-article h1 {
    font-size: 28px;
  }
}
"""


@dataclass
class Page:
    source_path: Path
    source_rel: Path
    output_rel: Path
    title: str
    category: str
    excerpt: str
    version: str | None
    updated_at: str | None
    audience: str | None


def render_site_nav(
    *,
    home_href: str,
    dashboard_href: str,
    details_href: str,
    manuals_href: str,
    costs_href: str,
    current: str,
) -> str:
    links = [
        ("首页", home_href, "home"),
        ("仪表盘", dashboard_href, "dashboard"),
        ("详细页", details_href, "details"),
        ("文档中心", manuals_href, "manuals"),
        ("成本维护台", costs_href, "costs"),
    ]
    rendered = "".join(
        f'<a class="top-nav-link{" is-active" if key == current else ""}" href="{href}">{label}</a>'
        for label, href, key in links
    )
    return f'<nav class="top-nav"><div class="top-nav-links">{rendered}</div></nav>'


def render_rail_panel(title: str, note: str, items: list[tuple[str, str, bool]]) -> str:
    links = "".join(
        f'<a class="{"current" if is_current else ""}" href="{href}">{label}</a>'
        for label, href, is_current in items
    )
    return (
        f'<section class="rail-panel"><h2>{html.escape(title)}</h2><p>{html.escape(note)}</p>'
        f'<div class="rail-links">{links}</div></section>'
    )


def collect_markdown_files() -> list[Path]:
    files: list[Path] = []
    for path in DOCS_DIR.rglob("*.md"):
        rel = path.relative_to(DOCS_DIR)
        if any(part in SKIP_PARTS for part in rel.parts):
            continue
        if path.name in SKIP_NAMES:
            continue
        files.append(path)
    return sorted(files, key=sort_key)


def sort_key(path: Path) -> tuple[int, int, str]:
    rel = path.relative_to(DOCS_DIR)
    if rel.parts[0] == "dashboard":
        order = 900
        num = 0
    else:
        match = re.match(r"(\d+)-", rel.name)
        num = int(match.group(1)) if match else 999
        order = num
    return (order, num, rel.as_posix())


def page_category(rel: Path) -> str:
    if rel.parts[0] == "dashboard":
        return "仪表盘输出"
    match = re.match(r"(\d+)-", rel.name)
    num = int(match.group(1)) if match else 999
    if num == 0:
        return "总导航"
    if 1 <= num <= 5:
        return "内容增长线"
    if 6 <= num <= 7:
        return "店铺经营基础"
    if 8 <= num <= 11:
        return "小团队管理线"
    if 12 <= num <= 15:
        return "引流与成交"
    if 16 <= num <= 18:
        return "库存与进货"
    if 19 <= num <= 21:
        return "会员与扩品"
    if 22 <= num <= 24:
        return "看板与数据"
    if 25 <= num <= 29:
        return "Pages 与发布"
    return "其他"


def output_rel_for(rel: Path) -> Path:
    return rel.with_suffix(".html")


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def extract_metadata(text: str) -> tuple[str | None, str | None, str | None]:
    version = None
    updated_at = None
    audience = None
    for line in text.splitlines()[:12]:
        stripped = line.strip()
        if stripped.startswith("版本："):
            version = stripped.removeprefix("版本：").strip()
        elif stripped.startswith("更新日期："):
            updated_at = stripped.removeprefix("更新日期：").strip()
        elif stripped.startswith("更新时间："):
            updated_at = stripped.removeprefix("更新时间：").strip()
        elif stripped.startswith("适用对象："):
            audience = stripped.removeprefix("适用对象：").strip()
    return version, updated_at, audience


def extract_excerpt(text: str) -> str:
    lines = text.splitlines()
    candidates: list[str] = []
    skip_prefixes = ("#", "版本：", "更新时间：", "更新日期：", "适用对象：", "|", "---")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(skip_prefixes):
            continue
        if stripped.startswith(("- ", "* ", "1.", "2.", "3.", "4.", "5.")):
            continue
        candidates.append(stripped)
        if len(candidates) >= 1:
            break
    return candidates[0] if candidates else "查看这份文档的完整内容。"


def rewrite_markdown_links(text: str, current_source: Path, current_output: Path) -> str:
    source_dir = current_source.parent
    output_dir = current_output.parent

    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            return match.group(0)
        if target.lower().startswith("javascript:"):
            return match.group(0)

        base, hash_part = (target.split("#", 1) + [""])[:2]
        target_path = Path(base)

        if target_path.suffix.lower() == ".md":
            resolved = (source_dir / target_path).resolve()
            try:
                resolved_rel = resolved.relative_to(DOCS_DIR)
            except ValueError:
                return match.group(0)
            destination = OUTPUT_DIR / output_rel_for(resolved_rel)
            rel_link = os.path.relpath(destination, output_dir).replace(os.sep, "/")
            if hash_part:
                rel_link = f"{rel_link}#{hash_part}"
            return f"[{label}]({rel_link})"

        return match.group(0)

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, text)


def render_page(page: Page, body_html: str, toc_html: str, prev_page: Page | None, next_page: Page | None) -> str:
    page_path = OUTPUT_DIR / page.output_rel
    home_href = os.path.relpath(DOCS_DIR / "index.html", page_path.parent).replace(os.sep, "/")
    dashboard_href = os.path.relpath(DOCS_DIR / "dashboard" / "index.html", page_path.parent).replace(os.sep, "/")
    details_href = os.path.relpath(DOCS_DIR / "dashboard" / "details.html", page_path.parent).replace(os.sep, "/")
    index_href = os.path.relpath(OUTPUT_DIR / "index.html", page_path.parent).replace(os.sep, "/")
    costs_href = os.path.relpath(DOCS_DIR / "costs" / "index.html", page_path.parent).replace(os.sep, "/")
    source_href = os.path.relpath(page.source_path, page_path.parent).replace(os.sep, "/")

    meta_bits = [f'<span class="meta-chip">{html.escape(page.category)}</span>']
    if page.version:
        meta_bits.append(f'<span class="meta-chip">版本：{html.escape(page.version)}</span>')
    if page.updated_at:
        meta_bits.append(f'<span class="meta-chip">更新时间：{html.escape(page.updated_at)}</span>')
    if page.audience:
        meta_bits.append(f'<span class="meta-chip">适用对象：{html.escape(page.audience)}</span>')

    footer_cards: list[str] = []
    if prev_page:
        prev_href = os.path.relpath(OUTPUT_DIR / prev_page.output_rel, page_path.parent).replace(os.sep, "/")
        footer_cards.append(
            f'<div class="footer-card"><div class="label">上一篇</div><a href="{prev_href}">{html.escape(prev_page.title)}</a>'
            f'<p>{html.escape(prev_page.category)}</p></div>'
        )
    if next_page:
        next_href = os.path.relpath(OUTPUT_DIR / next_page.output_rel, page_path.parent).replace(os.sep, "/")
        footer_cards.append(
            f'<div class="footer-card"><div class="label">下一篇</div><a href="{next_href}">{html.escape(next_page.title)}</a>'
            f'<p>{html.escape(next_page.category)}</p></div>'
        )
    footer_cards.append(
        f'<div class="footer-card"><div class="label">源文件</div><a href="{source_href}">查看 Markdown 源文档</a>'
        f'<p>如果你要继续修改内容，优先改这份源文件。</p></div>'
    )

    site_nav = render_site_nav(
        home_href=home_href,
        dashboard_href=dashboard_href,
        details_href=details_href,
        manuals_href=index_href,
        costs_href=costs_href,
        current="manuals",
    )
    global_nav = render_rail_panel(
        "常用导航",
        "不管你现在在哪份手册里，都能从这里直接回到最常用的页面。",
        [
            ("Pages 首页", home_href, False),
            ("经营仪表盘", dashboard_href, False),
            ("详细经营页", details_href, False),
            ("文档中心", index_href, True),
            ("成本维护台", costs_href, False),
        ],
    )

    toc_panel = ""
    if toc_html.strip():
        toc_panel = (
            '<section class="toc-panel"><h2>页内目录</h2><p>先扫一眼目录，再按需要往下看，手机上也能直接跳到对应章节。</p>'
            f"{toc_html}</section>"
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(page.title)} | 小黑托昵文档中心</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="page">
    {site_nav}
    <section class="hero">
      <h1>{html.escape(page.title)}</h1>
      <p>{html.escape(page.excerpt)}</p>
      <div class="hero-actions">
        <a class="btn-primary" href="{home_href}">返回 Pages 首页</a>
        <a class="btn-secondary" href="{index_href}">进入文档中心</a>
        <a class="btn-secondary" href="{dashboard_href}">打开经营仪表盘</a>
      </div>
      <div class="breadcrumbs">
        <a class="nav-chip" href="{home_href}">Pages 首页</a>
        <a class="nav-chip" href="{index_href}">文档中心</a>
        <span class="nav-chip">{html.escape(page.title)}</span>
      </div>
      <div class="meta-row">
        {''.join(meta_bits)}
      </div>
    </section>

    <div class="page-shell">
      <div class="main-column">
        <div class="doc-layout" style="margin-top:0;">
          <article class="doc-article">
            {body_html}
            <div class="doc-footer">
              {''.join(footer_cards)}
            </div>
            <div class="footer-note">
              这页内容由 Markdown 自动生成。继续编辑时，优先修改源 Markdown，再重新运行生成脚本。
            </div>
          </article>
        </div>
      </div>
      <aside class="side-rail">
        {global_nav}
        {toc_panel}
      </aside>
    </div>
  </div>
</body>
</html>
"""


def render_index(pages: list[Page]) -> str:
    grouped: dict[str, list[Page]] = {label: [] for label in DOC_CATEGORY_ORDER}
    for page in pages:
        grouped.setdefault(page.category, []).append(page)

    sections: list[str] = []
    rail_items: list[tuple[str, str, bool]] = []
    section_index = 0
    for label in DOC_CATEGORY_ORDER:
        items = grouped.get(label) or []
        if not items:
            continue
        section_index += 1
        section_id = f"manual-group-{section_index}"
        rail_items.append((label, f"#{section_id}", False))
        cards = []
        for page in items:
            href = page.output_rel.as_posix()
            details = []
            if page.version:
                details.append(f"版本：{page.version}")
            if page.updated_at:
                details.append(f"更新时间：{page.updated_at}")
            if page.audience:
                details.append(f"适用对象：{page.audience}")
            detail_text = " / ".join(details) if details else "网页阅读版"
            cards.append(
                f'<article class="card"><div class="card-kicker">{html.escape(page.category)}</div>'
                f'<h3>{html.escape(page.title)}</h3><p>{html.escape(page.excerpt)}</p>'
                f'<p class="section-note">{html.escape(detail_text)}</p>'
                f'<a href="{href}">打开 HTML 文档</a></article>'
            )
        sections.append(
            f'<section class="section" id="{section_id}"><h2>{html.escape(label)}</h2><p class="section-note">这一组文档已经整理成网页阅读版，适合老板、店员和协作人员直接在 Pages 里浏览。</p>'
            f'<div class="grid">{"".join(cards)}</div></section>'
        )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    site_nav = render_site_nav(
        home_href="../index.html",
        dashboard_href="../dashboard/index.html",
        details_href="../dashboard/details.html",
        manuals_href="./index.html",
        costs_href="../costs/index.html",
        current="manuals",
    )
    global_nav = render_rail_panel(
        "常用导航",
        "这里是所有手册的入口，但老板日常更适合先去仪表盘。",
        [
            ("Pages 首页", "../index.html", False),
            ("经营仪表盘", "../dashboard/index.html", False),
            ("详细经营页", "../dashboard/details.html", False),
            ("文档中心", "./index.html", True),
            ("成本维护台", "../costs/index.html", False),
        ],
    )
    category_nav = render_rail_panel(
        "文档分类",
        "先选一条主线，再进具体文档，会比整页上下翻更顺。",
        rail_items,
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>小黑托昵文档中心</title>
  <style>{CSS}</style>
</head>
<body>
  <div class="page">
    {site_nav}
    <section class="hero">
      <h1>小黑托昵文档中心</h1>
      <p>这里收的是 `docs/` 目录下的网页阅读版文档。老板可以直接读策略和经营手册，员工也可以用手机打开培训、接待、检查清单，不需要再看原始 Markdown。</p>
      <div class="hero-actions">
        <a class="btn-primary" href="../index.html">返回 Pages 首页</a>
        <a class="btn-secondary" href="../dashboard/index.html">打开经营仪表盘</a>
      </div>
      <div class="meta-row">
        <span class="meta-chip">生成时间：{generated_at}</span>
        <span class="meta-chip">文档范围：docs/*.md 与 docs/dashboard/*.md</span>
      </div>
    </section>

    <div class="page-shell">
      <div class="main-column">
        <section class="section" id="manual-guide">
          <h2>怎么用最顺</h2>
          <p class="section-note">如果你是老板，建议先看经营基础、库存与进货、会员与扩品；如果你是员工，优先看小团队管理线和接待成交。所有文档都保留源 Markdown，不影响后续继续修改。</p>
        </section>

        {''.join(sections)}
      </div>
      <aside class="side-rail">
        {global_nav}
        {category_nav}
      </aside>
    </div>
  </div>
</body>
</html>
"""


def build_pages() -> list[Page]:
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_files = collect_markdown_files()
    pages: list[Page] = []
    for source_path in source_files:
        rel = source_path.relative_to(DOCS_DIR)
        text = source_path.read_text(encoding="utf-8")
        title = extract_title(text, source_path.stem)
        version, updated_at, audience = extract_metadata(text)
        pages.append(
            Page(
                source_path=source_path,
                source_rel=rel,
                output_rel=output_rel_for(rel),
                title=title,
                category=page_category(rel),
                excerpt=extract_excerpt(text),
                version=version,
                updated_at=updated_at,
                audience=audience,
            )
        )

    for index, page in enumerate(pages):
        source_text = page.source_path.read_text(encoding="utf-8")
        rewritten = rewrite_markdown_links(source_text, page.source_path, OUTPUT_DIR / page.output_rel)
        md = markdown.Markdown(
            extensions=["tables", "fenced_code", "toc", "sane_lists"],
            extension_configs={"toc": {"permalink": "¶"}},
        )
        body_html = md.convert(rewritten)
        toc_html = md.toc
        output_path = OUTPUT_DIR / page.output_rel
        output_path.parent.mkdir(parents=True, exist_ok=True)
        prev_page = pages[index - 1] if index > 0 else None
        next_page = pages[index + 1] if index + 1 < len(pages) else None
        output_path.write_text(
            render_page(page, body_html, toc_html, prev_page, next_page),
            encoding="utf-8",
        )

    (OUTPUT_DIR / "index.html").write_text(render_index(pages), encoding="utf-8")
    return pages


def main() -> int:
    pages = build_pages()
    print(f"Generated {len(pages)} HTML documents under {OUTPUT_DIR}")
    print(f"Docs center: {OUTPUT_DIR / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
