#!/usr/bin/env python3
"""Rendering helpers for the inventory dashboard pages."""

from __future__ import annotations

import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def fig_to_html(fig: go.Figure, include_js: bool = False) -> str:
    return fig.to_html(
        full_html=False,
        include_plotlyjs="cdn" if include_js else False,
        config={
            "responsive": True,
            "displaylogo": False,
            "scrollZoom": False,
            "modeBarButtonsToRemove": [
                "lasso2d",
                "select2d",
                "autoScale2d",
                "toggleSpikelines",
                "hoverClosestCartesian",
                "hoverCompareCartesian",
            ],
        },
    )


def build_charts(metrics: dict) -> list[str]:
    charts: list[str] = []
    profit_history = metrics.get("profit_history")

    if profit_history and len(profit_history["rows"]) >= 2:
        history_df = pd.DataFrame(profit_history["rows"]).copy()
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=history_df["月份"],
                y=history_df["销售额"],
                mode="lines+markers",
                name="销售额",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=history_df["月份"],
                y=history_df["净利润"],
                mode="lines+markers",
                name="净利润",
            )
        )
        fig.add_trace(
            go.Bar(
                x=history_df["月份"],
                y=history_df["总费用"],
                name="总费用",
                opacity=0.45,
            )
        )
        fig.update_layout(
            title="月度利润与费用趋势",
            height=420,
            margin=dict(l=20, r=20, t=60, b=20),
            barmode="group",
        )
        charts.append(fig_to_html(fig, include_js=True))

    daily = metrics["sales_daily"]
    if not daily.empty:
        fig = px.line(
            daily,
            x="日期",
            y="销售额",
            markers=True,
            title="每日经营销售额走势（已剔除道具）",
            text="订单数",
        )
        fig.update_traces(textposition="top center")
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig, include_js=True))

    cat_sales = metrics["sales_by_category_ex_props"].head(8)
    if not cat_sales.empty:
        fig = px.bar(
            cat_sales,
            x="商品大类",
            y="销售额",
            color="销量",
            title="经营销售额最高的品类（已剔除道具）",
            text_auto=".2s",
        )
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    cat_inv = metrics["inventory_by_category"].head(10)
    if not cat_inv.empty:
        fig = px.bar(
            cat_inv,
            x="大类",
            y="库存额",
            color="库存量",
            title="经营库存金额最高的品类（已剔除道具）",
            text_auto=".2s",
        )
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    ratio = metrics["category_risks"].head(10)
    if not ratio.empty:
        fig = px.scatter(
            ratio,
            x="零售额",
            y="库存额",
            size="库存金额/销售金额",
            color="大类",
            hover_data=["库存金额/销售金额", "库存量/销售量"],
            title="经营品类库存额 vs 销售额（已剔除道具）",
        )
        fig.update_layout(height=440, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    guide = metrics["guide_perf"]
    if not guide.empty:
        fig = px.bar(
            guide,
            x="导购员",
            y="实收金额",
            color="连带",
            title="导购业绩对比",
            text_auto=".2s",
            hover_data=["票数", "单效", "会员销额"],
        )
        fig.update_layout(height=420, margin=dict(l=20, r=20, t=60, b=20))
        charts.append(fig_to_html(fig))

    return charts


def format_badge(value: str, level: str, tip: str | None = None) -> str:
    safe_value = html.escape(value)
    classes = f"badge badge-{level}"
    attrs = ""
    if tip:
        safe_tip = html.escape(tip, quote=True)
        classes += " tooltip-badge"
        attrs = f' title="{safe_tip}" data-tip="{safe_tip}" tabindex="0" role="note"'
    return f"<span class='{classes}'{attrs}>{safe_value}</span>"


def inline_tip(label: str, tip: str) -> str:
    safe_label = html.escape(label)
    safe_tip = html.escape(tip, quote=True)
    return f"<span class='inline-tip tooltip-badge' title='{safe_tip}' data-tip='{safe_tip}' tabindex='0' role='note'>{safe_label}</span>"


def floating_tooltip_css() -> str:
    return """
    .tooltip-badge::after,
    .tooltip-badge::before {
      display: none !important;
      content: none !important;
    }
    .floating-tooltip {
      position: fixed;
      left: 0;
      top: 0;
      z-index: 9999;
      max-width: min(420px, calc(100vw - 24px));
      background: #0f172a;
      color: #ffffff;
      border-radius: 14px;
      padding: 12px 14px;
      line-height: 1.7;
      font-size: 12px;
      font-weight: 500;
      box-shadow: 0 18px 36px rgba(15, 23, 42, 0.28);
      opacity: 0;
      pointer-events: none;
      transform: translateY(4px);
      transition: opacity 0.16s ease, transform 0.16s ease;
      white-space: normal;
      word-break: break-word;
    }
    .floating-tooltip.is-visible {
      opacity: 1;
      transform: translateY(0);
    }
    """


def floating_tooltip_script() -> str:
    return """
  <script>
    (function () {
      if (window.__blackTonnyTooltipInit) return;
      window.__blackTonnyTooltipInit = true;

      const tooltip = document.createElement('div');
      tooltip.className = 'floating-tooltip';
      document.body.appendChild(tooltip);

      let activeTarget = null;

      function hideTooltip() {
        activeTarget = null;
        tooltip.classList.remove('is-visible');
      }

      function showTooltip(target) {
        const message = target.getAttribute('data-tip') || target.getAttribute('title');
        if (!message) return;
        activeTarget = target;
        tooltip.textContent = message;
        tooltip.classList.add('is-visible');

        const rect = target.getBoundingClientRect();
        const ttRect = tooltip.getBoundingClientRect();
        const margin = 12;
        let left = rect.left + rect.width / 2 - ttRect.width / 2;
        left = Math.max(margin, Math.min(left, window.innerWidth - ttRect.width - margin));
        let top = rect.top - ttRect.height - 12;
        if (top < margin) {
          top = rect.bottom + 12;
        }
        tooltip.style.left = `${left}px`;
        tooltip.style.top = `${top}px`;
      }

      function attachTooltip(target) {
        target.addEventListener('mouseenter', () => showTooltip(target));
        target.addEventListener('mouseleave', hideTooltip);
        target.addEventListener('focus', () => showTooltip(target));
        target.addEventListener('blur', hideTooltip);
        target.addEventListener('click', (event) => {
          event.stopPropagation();
          if (activeTarget === target && tooltip.classList.contains('is-visible')) {
            hideTooltip();
          } else {
            showTooltip(target);
          }
        });
      }

      document.querySelectorAll('.tooltip-badge').forEach(attachTooltip);
      window.addEventListener('scroll', hideTooltip, { passive: true });
      window.addEventListener('resize', () => {
        if (activeTarget) showTooltip(activeTarget);
      });
      document.addEventListener('click', (event) => {
        if (!event.target.closest('.tooltip-badge')) {
          hideTooltip();
        }
      });
    })();
  </script>
    """


def note_with_tip(summary: str, tip: str, label: str = "查看说明") -> str:
    return f"{html.escape(summary)} {inline_tip(label, tip)}"


def insight_item(summary: str, detail: str | None = None, label: str = "说明") -> dict[str, str]:
    item = {"summary": summary}
    if detail:
        item["detail"] = detail
        item["label"] = label
    return item


def render_insights_html(items: list[dict[str, str] | str]) -> str:
    rendered: list[str] = []
    for item in items:
        if isinstance(item, dict):
            summary = item.get("summary", "")
            detail = item.get("detail")
            if detail:
                rendered.append(f"<li>{note_with_tip(summary, detail, item.get('label', '说明'))}</li>")
            else:
                rendered.append(f"<li>{html.escape(summary)}</li>")
        else:
            rendered.append(f"<li>{html.escape(str(item))}</li>")
    return "".join(rendered)


def render_insights_markdown(items: list[dict[str, str] | str]) -> list[str]:
    lines: list[str] = []
    for item in items:
        if isinstance(item, dict):
            lines.append(item.get("summary", ""))
        else:
            lines.append(str(item))
    return lines


def compact_sentence_with_tip(text: str, label: str = "说明") -> str:
    segments = [segment.strip() for segment in text.replace("；", "，").split("，") if segment.strip()]
    if len(segments) <= 1:
        return html.escape(text)
    summary = segments[0]
    if not summary.endswith(("。", "！", "？")):
        summary += "。"
    detail = "，".join(segments[1:])
    return note_with_tip(summary, detail, label)


def render_time_strategy_html(time_strategy: dict) -> str:
    blocks = [
        ("今天", time_strategy["daily_actions"]),
        ("本周", time_strategy["weekly_actions"]),
        ("本月", time_strategy["monthly_actions"]),
    ]
    rows: list[str] = [
        f"<li>北京时间：{html.escape(time_strategy['beijing_time'])}</li>",
        f"<li>当前判断：{html.escape(time_strategy['headline'])}</li>",
    ]
    for title, actions in blocks:
        for action in actions:
            rows.append(f"<li><strong>{title}</strong>：{compact_sentence_with_tip(action, '补充')}</li>")
    return "".join(rows)


def table_text_with_tip(value: object, max_len: int = 12, label: str = "详情") -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if len(text) <= max_len:
        return html.escape(text)
    short = html.escape(text[:max_len].rstrip() + "…")
    return f"{short} {inline_tip(label, text)}"


def safe_cell_html(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value)
    if "<" in text and ">" in text:
        return text
    return html.escape(text)


def render_empty(message: str) -> str:
    return f"<div class='empty-card'>{html.escape(message)}</div>"


def compact_list_html(
    df: pd.DataFrame,
    title: str,
    rows: int,
    tip: str,
    title_fn,
    subtitle_fn,
    stats_fn,
    detail_fn=None,
) -> str:
    preview = df.head(rows).copy()
    if preview.empty:
        return render_empty(f"{title} 当前没有可展示数据。")

    items_html: list[str] = []
    for _, row in preview.iterrows():
        stats = "".join(stats_fn(row))
        detail_html = ""
        if detail_fn is not None:
            details = [item for item in detail_fn(row) if item]
            if details:
                detail_html = (
                    "<details class='compact-more'>"
                    "<summary>查看补充信息</summary>"
                    f"<ul class='compact-detail-list'>{''.join(f'<li>{html.escape(str(item))}</li>' for item in details)}</ul>"
                    "</details>"
                )
        items_html.append(
            f"""
            <article class="compact-item">
              <div class="compact-item-head">
                <div class="compact-item-title">{html.escape(str(title_fn(row)))}</div>
                <div class="compact-item-subtitle">{html.escape(str(subtitle_fn(row)))}</div>
              </div>
              <div class="compact-stats">{stats}</div>
              {detail_html}
            </article>
            """
        )

    return f"""
    <section class="table-card compact-card">
      <div class="table-header">
        <h3>{title}</h3>
      </div>
      <p class="table-tip">{tip}</p>
      <div class="compact-list">
        {''.join(items_html)}
      </div>
    </section>
    """
