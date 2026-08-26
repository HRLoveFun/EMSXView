"""TCA 独立 HTML 报告渲染器 — 纯 Python 生成自包含静态 HTML。

零外部依赖：内联 CSS + 服务端生成 SVG 图表（无 JS），
浏览器直接打开即可查看，可邮件分发、离线归档。

报告结构：
    报告头（标题/生成时间/过滤条件/口径脚注） → KPI 卡片 →
    pnl_vwap 直方图 + 按日走势 → broker/algo 排行 + PWP 曲线 →
    市场冲击分解表 → 异常路由明细表 → 指标覆盖率表 → BDIB 缺口附录 → 页脚

口径脚注：报告为价格偏离口径，不含显性费用/返佣/税费；无 L2 订单簿流动性；
不含事前预测；机会成本按 (Pn−P0)×未成交×方向计。
（对应 docs/report-tca-known-limitations.md 清单）
"""

from __future__ import annotations

from typing import Any, Optional

from DataPipeline.config import Config

# ── SVG 画布常量 ──
_CHART_W = 780
_CHART_H = 260
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 52, 16, 16, 32

#: pnl_vwap 为成本指标：正(差)红 / 负(优)绿
_COLOR_POS = "#ef5350"
_COLOR_NEG = "#26a69a"
_COLOR_LINE1 = "#4fc3f7"
_COLOR_LINE2 = "#ffb74d"
_COLOR_BAR = "#4fc3f7"


def render_report_html(
    report: dict[str, Any],
    health: Optional[dict[str, Any]],
    generated_at: str,
) -> str:
    """渲染完整报告 HTML。"""
    filters = report.get("filters", {})
    title_range = f"{filters.get('start_date', '')} ~ {filters.get('end_date', '')}"
    sections = [
        _html_head(f"TCA 可视化报告 {title_range}"),
        _render_header(filters, generated_at),
        _render_market_tabs(report.get("markets"), report.get("kpi")),
        _render_kpi_cards(report.get("kpi"), report.get("extra_kpis"),
                          report.get("anomaly")),
        _render_charts(report),
        _render_impact_breakdown(report.get("impact_breakdown")),
        _render_anomaly_table(report.get("anomaly")),
        _render_coverage_table(report.get("metric_coverage")),
        _render_health_appendix(health),
        _render_footer(),
        "</body></html>",
    ]
    return "\n".join(s for s in sections if s)


# ═══════════════════════════════════════════════════════════════════════════
# 页面骨架
# ═══════════════════════════════════════════════════════════════════════════


def _html_head(title: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
:root {{ color-scheme: dark; }}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #0f1419; color: #d7dee8; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; padding: 24px; }}
.container {{ max-width: 1280px; margin: 0 auto; }}
h1 {{ font-size: 22px; color: #eceff4; }}
h2 {{ font-size: 16px; color: #9fb3c8; margin: 28px 0 12px; border-left: 3px solid #4fc3f7; padding-left: 10px; }}
.meta {{ color: #7d8fa3; font-size: 13px; margin-top: 6px; }}
.meta span {{ margin-right: 16px; }}
.disclaimer {{ color: #5f7186; font-size: 11px; margin-top: 8px; border-top: 1px solid #22304a; padding-top: 6px; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-top: 20px; }}
.card {{ background: #1a2332; border: 1px solid #2a3648; border-radius: 8px; padding: 14px 16px; }}
.card .label {{ font-size: 12px; color: #7d8fa3; }}
.card .value {{ font-size: 24px; font-weight: 600; color: #eceff4; margin-top: 6px; }}
.card .sub {{ font-size: 11px; color: #5f7186; margin-top: 4px; }}
.panel {{ background: #1a2332; border: 1px solid #2a3648; border-radius: 8px; padding: 16px; margin-top: 12px; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
@media (max-width: 1100px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
th, td {{ padding: 5px 8px; text-align: right; border-bottom: 1px solid #22304a; white-space: nowrap; }}
th {{ color: #7d8fa3; font-weight: 500; position: sticky; top: 0; background: #1a2332; }}
td.l, th.l {{ text-align: left; }}
.warn {{ background: #3a2a1a; border: 1px solid #8a5a2a; border-radius: 8px; padding: 12px 16px; margin-top: 12px; color: #ffb74d; font-size: 13px; }}
.tag {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }}
.tag-ok {{ background: #1b3a2f; color: #26a69a; }}
.tag-partial {{ background: #3a3418; color: #ffca28; }}
.tag-missing {{ background: #3a1f1f; color: #ef5350; }}
.tag-unrecoverable {{ background: #2a2f38; color: #90a4ae; }}
.footer {{ margin-top: 32px; color: #5f7186; font-size: 11px; text-align: center; }}
svg text {{ font-family: inherit; }}
/* 007: 分市场 CSS 标签页（零 JS，radio 驱动，无锚点跳转） */
.tab-wrap {{ margin-top: 16px; display: flex; flex-wrap: wrap; gap: 6px; }}
.tab-wrap > input[type="radio"] {{ display: none; }}
.tab-wrap > label {{ padding: 4px 14px; border-radius: 14px; font-size: 12px; color: #7d8fa3;
  background: #1a2332; border: 1px solid #2a3648; cursor: pointer; user-select: none; }}
.tab-wrap > label:hover {{ color: #d7dee8; border-color: #4fc3f7; }}
.tab-wrap > input[type="radio"]:checked + label {{ background: #4fc3f7; color: #0f1419; font-weight: 600; border-color: #4fc3f7; }}
.mk-panel {{ display: none; flex-basis: 100%; margin-top: 10px; }}
</style></head><body><div class="container">"""


def _render_header(filters: dict[str, Any], generated_at: str) -> str:
    """报告头：标题 + 过滤条件摘要 + 口径脚注。"""
    cond = [f"日期 {filters.get('start_date')} ~ {filters.get('end_date')}"]
    for key, label in (("broker", "Broker"), ("algo", "Algo"),
                       ("symbol", "Symbol"), ("exchange", "市场")):
        if filters.get(key):
            cond.append(f"{label}={filters[key]}")
    metrics = filters.get("metrics") or []
    cond.append(f"覆盖率指标 {len(metrics)} 项")
    cond_html = "".join(f"<span>{_esc(c)}</span>" for c in cond)
    return f"""
<h1>TCA 可视化报告 <span style="font-size:14px;color:#7d8fa3">tca_route_summary</span></h1>
<div class="meta"><span>生成时间 {_esc(generated_at)}</span>{cond_html}</div>
<div class="disclaimer">口径：价格偏离（不含显性费用/返佣/税费）；无 L2 订单簿流动性；不含事前预测；机会成本按 (Pn−P0)×未成交×方向计。</div>"""


def _render_footer() -> str:
    """页脚：口径脚注重复 + 数据源。"""
    return (
        '<div class="footer">'
        "EMSXView CostView · 数据源 tca_route_summary / fill_bdib / raw_bdib · "
        "口径：价格偏离，不含显性费用/返佣/税费；无 L2 订单簿流动性；不含事前预测"
        "</div>"
    )


def _render_market_tabs(
    markets: Optional[list[dict[str, Any]]],
    kpi: Optional[dict[str, Any]],
) -> str:
    """分市场标签页（007）：市场由 Config.MARKET_ORDER 设定顺序。

    零 JS 实现：radio 驱动的纯 CSS 标签页（选中态为 ``:checked + label``，
    面板用兄弟选择器 ``:checked ~ .mk-panels`` 显示）。默认选中「全部」，
    切换不产生页面锚点跳转（区别于早期 :target 方案）。每个市场锚点指向
    市场汇总表（route 数 + 成交金额 USD）。
    """
    if not markets:
        return ""
    # 按 Config.MARKET_ORDER 排序（未配置的市场排后面，中文名缺失用代码）
    order = Config.MARKET_ORDER
    known = [m for m in markets if m["exchange"] in order]
    unknown = [m for m in markets if m["exchange"] not in order]
    known.sort(key=lambda m: list(order.keys()).index(m["exchange"]))
    unknown.sort(key=lambda m: m["exchange"])
    ordered = known + unknown
    if len(ordered) < 2:
        return ""

    radios = [f'<input type="radio" name="mk" id="mk-all" checked>'
              f'<label for="mk-all">全部</label>']
    panels = ['<div class="mk-panel">']
    panels.append(_market_summary_table(ordered, is_all=True))
    panels.append("</div>")
    for i, m in enumerate(ordered):
        code = m["exchange"]
        display = order.get(code, code)
        radios.append(f'<input type="radio" name="mk" id="mk-{code}">'
                      f'<label for="mk-{code}">{_esc(display)}</label>')
        panels.append(f'<div class="mk-panel">')
        panels.append(_market_summary_table([m], is_all=False))
        panels.append("</div>")
    # 面板跟随选中的 radio 兄弟显示（通用兄弟选择器，无锚点跳转）
    # radio / label / .mk-panel 均为 .tab-wrap 直接子元素；默认「全部」checked
    # panel 1 = 全部，市场 i → panel i+2
    show = "".join(
        f'input#mk-{_css_id(m["exchange"])}:checked ~ .mk-panel:nth-of-type({i + 2})'
        f'{{ display:block; }}'
        for i, m in enumerate(ordered)
    )
    return f"""
<h2>分市场概览</h2>
<div class="tab-wrap">
{''.join(radios)}
<style>{show}
input#mk-all:checked ~ .mk-panel:nth-of-type(1) {{ display:block; }}
</style>
{''.join(panels)}
</div>"""


def _market_summary_table(
    markets: list[dict[str, Any]], is_all: bool,
) -> str:
    """市场汇总表：route 数 + 成交金额（本币 / USD）。"""
    rows = "".join(
        f'<tr><td class="l">{_esc(Config.MARKET_ORDER.get(m["exchange"], m["exchange"]))}</td>'
        f'<td class="l">{_esc(m["exchange"])}</td>'
        f"<td>{m['route_count']:,}</td>"
        f"<td>{_fmt_big(m.get('notional'))}</td>"
        f"<td>{_fmt_big(m.get('notional_usd'))}</td></tr>"
        for m in markets
    )
    title = "全部市场" if is_all else f"{_esc(Config.MARKET_ORDER.get(markets[0]['exchange'], markets[0]['exchange']))} 市场"
    return f"""
<div class="panel" style="overflow-x:auto">
<table><thead><tr><th class="l">市场</th><th class="l">代码</th><th>Route 数</th>
<th>成交金额（本币）</th><th>成交金额（美元）</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="meta" style="margin-top:8px">市场顺序与白名单由 DataPipeline/config.py::Config.MARKET_ORDER 设定。</div>
</div>"""


def _render_kpi_cards(
    kpi: Optional[dict[str, Any]],
    extra: Optional[dict[str, Any]],
    anomaly: Optional[dict[str, Any]],
) -> str:
    """KPI 卡片区：整体水位（5）+ 基准/短缺/风险/完成率/异常（5）。"""
    if not kpi:
        return '<div class="warn">tca_route_summary 无数据 — 请先运行管道 S5.5。</div>'
    cards = [
        ("Route 总数", f"{kpi['route_count']:,}", ""),
        ("总成交股数", _fmt_big(kpi["total_route_shares"]), "RouteShares 合计"),
        # 007: 总成交金额（USD 换算，标注 fx_rate 覆盖率）
        ("总成交金额（美元）", _fmt_big(kpi.get("notional_usd")), _fx_coverage_sub(kpi)),
        ("加权 pnl_vwap", _fmt_num(kpi.get("weighted_pnl_vwap")), "成交额加权 · VWAP 基准"),
        ("平均 par_rate", _fmt_num(kpi.get("avg_par_rate")), "参与率均值"),
        ("平均 RPM", _fmt_num(kpi.get("avg_rpm")), ""),
    ]
    if extra:
        cards += [
            ("加权 arrival 成本", _fmt_num(extra.get("arrival_cost_bps")), "决策基准 · 成交额加权"),
            ("加权 IS (bps)", _fmt_num(extra.get("wagner_is_bps")), "实现短缺 · 成交额加权"),
            ("成本风险 stddev/CVaR", _fmt_risk(extra.get("cost_stddev"), extra.get("cost_cvar")), "尾部风险"),
            ("平均完成率", _fmt_pct(extra.get("avg_fill")), "fill 均值"),
        ]
    if anomaly is not None:
        cards.append(
            ("异常路由", f"{anomaly.get('count', 0):,}", (
                f"critical {anomaly.get('critical_count', 0)} · 见下方明细"
            )),
        )
    inner = "".join(
        f'<div class="card"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div>'
        f'<div class="sub">{_esc(sub)}</div></div>'
        for label, value, sub in cards
    )
    return f'<div class="cards">{inner}</div>'


# ═══════════════════════════════════════════════════════════════════════════
# 图表区
# ═══════════════════════════════════════════════════════════════════════════


def _render_charts(report: dict[str, Any]) -> str:
    """四个图表面板：直方图 / 按日走势 / 排行 / PWP 曲线。"""
    histogram = _svg_histogram(report.get("pnl_vwap_histogram") or [])
    daily = _svg_daily_series(report.get("daily_series") or [])
    broker = _svg_hbar(report.get("rankings", {}).get("by_broker") or [], "Broker 排行（加权 pnl_vwap）")
    algo = _svg_hbar(report.get("rankings", {}).get("by_algo") or [], "Algo 排行（加权 pnl_vwap）")
    pwp = _svg_pwp_curve(report.get("pwp_curve") or [])
    return f"""
<h2>分布与走势</h2>
<div class="grid2">
  <div class="panel"><h2 style="margin-top:0">pnl_vwap 分布直方图</h2>{histogram}</div>
  <div class="panel"><h2 style="margin-top:0">按日加权 pnl_vwap / 平均 par_rate</h2>{daily}</div>
</div>
<h2>执行方排行</h2>
<div class="grid2">
  <div class="panel">{broker}</div>
  <div class="panel">{algo}</div>
</div>
<h2>PWP 分档均值</h2>
<div class="panel">{pwp}</div>"""


def _render_impact_breakdown(impact: Optional[dict[str, Any]]) -> str:
    """市场冲击分解表（B2-2）：暂时冲击 5/10/30min + 永久冲击。"""
    if not impact:
        return ""
    rows = [
        ("暂时冲击 5min", _fmt_num(impact.get("temp_impact_5min_bps")), "成交后 5 分钟价格恢复偏离"),
        ("暂时冲击 10min", _fmt_num(impact.get("temp_impact_10min_bps")), "成交后 10 分钟价格恢复偏离"),
        ("暂时冲击 30min", _fmt_num(impact.get("temp_impact_30min_bps")), "成交后 30 分钟价格恢复偏离"),
        ("永久冲击", _fmt_num(impact.get("perm_impact_bps")), "收盘价相对到达价的持续偏离"),
        ("收盘价成本", _fmt_num(impact.get("close_cost_bps")), "收盘价基准偏离"),
    ]
    body = "".join(
        f'<tr><td class="l">{_esc(label)}</td><td>{_esc(value)} bps</td>'
        f'<td class="l" style="white-space:normal">{_esc(desc)}</td></tr>'
        for label, value, desc in rows
    )
    return f"""
<h2>市场冲击分解</h2>
<div class="panel" style="overflow-x:auto">
<table><thead><tr><th class="l">冲击维度</th><th>加权值</th><th class="l">说明</th></tr></thead>
<tbody>{body}</tbody></table>
<div class="meta" style="margin-top:8px">成交额加权（RouteShares × p_avg）；恢复窗口越界时使用次日收盘价作跨日恢复价格。</div>
</div>"""


def _render_anomaly_table(anomaly: Optional[dict[str, Any]]) -> str:
    """异常路由明细表（S6）：触发阈值规则的路由逐单清单（无上限）。"""
    if anomaly is None:
        return ""
    rows = anomaly.get("rows") or []
    count = anomaly.get("count", len(rows))
    if not rows:
        return f"""
<h2>异常路由明细</h2>
<div class="panel">本期无异常路由（{_esc(str(count))} 条触发阈值）。</div>"""
    body_rows = []
    for r in rows:
        hits = r.get("hits") or []
        tags = "".join(
            f'<span class="tag tag-{"critical" if h["severity"] == "critical" else "warning"}">{_esc(h["label"])}</span>'
            for h in hits
        )
        body_rows.append(
            f'<tr>'
            f'<td><span class="tag tag-{_esc(r.get("severity", "warning"))}">{_esc(r.get("severity", ""))}</span></td>'
            f'<td class="l">{_esc(r.get("date", ""))}</td>'
            f'<td class="l">{_esc(r.get("order_id", ""))}</td>'
            f'<td class="l">{_esc(r.get("route_id", ""))}</td>'
            f'<td class="l">{_esc(r.get("ticker", ""))}</td>'
            f'<td class="l">{_esc(r.get("exchange") or "")}</td>'
            f'<td class="l">{_esc(r.get("side") or "")}</td>'
            f'<td class="l">{_esc(r.get("broker") or "")}</td>'
            f'<td class="l">{_esc(r.get("algo") or "")}</td>'
            f'<td>{_fmt_pct(r.get("completion_rate"))}</td>'
            f'<td>{_fmt_pct(r.get("par_rate"))}</td>'
            f'<td>{_fmt_num(r.get("pnl_vwap"))}</td>'
            f'<td>{_fmt_num(r.get("arrival_cost_bps"))}</td>'
            f'<td>{_fmt_num(r.get("wagner_is_bps"))}</td>'
            f'<td>{_fmt_num(r.get("opportunity_cost"))}</td>'
            f'<td>{_fmt_big(r.get("unfilled"))}</td>'
            f'<td>{_fmt_num(r.get("cost_cvar"))}</td>'
            f'<td>{_fmt_duration(r.get("order_duration_sec"))}</td>'
            f'<td>{_esc("1" if r.get("recovery_truncated") else "")}</td>'
            f'<td class="l" style="white-space:normal">{tags}</td>'
            f'</tr>'
        )
    return f"""
<h2>异常路由明细（{_esc(str(count))} 条）</h2>
<div class="panel" style="overflow-x:auto;max-height:520px;overflow-y:auto">
<table><thead><tr>
<th>严重度</th><th class="l">日期</th><th class="l">订单</th><th class="l">路由</th>
<th class="l">标的</th><th class="l">交易所</th><th class="l">方向</th><th class="l">Broker</th>
<th class="l">Algo</th><th>完成率</th><th>参与率</th><th>pnl_vwap</th>
<th>arrival</th><th>IS</th><th>机会成本</th><th>未成交</th><th>CVaR</th>
<th>历时</th><th>跨日</th><th class="l">命中规则</th>
</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"""


def _svg_histogram(buckets: list[dict[str, Any]]) -> str:
    """pnl_vwap 直方图（纵向柱形）。"""
    if not buckets:
        return _empty_hint("无 pnl_vwap 数据")
    counts = [b["count"] for b in buckets]
    max_c = max(counts) or 1
    n = len(buckets)
    plot_w = _CHART_W - _PAD_L - _PAD_R
    plot_h = _CHART_H - _PAD_T - _PAD_B
    bar_w = plot_w / n
    parts = [_svg_frame(max_c, "count")]
    for i, b in enumerate(buckets):
        h = b["count"] / max_c * plot_h
        x = _PAD_L + i * bar_w
        parts.append(
            f'<rect x="{x + 1:.1f}" y="{_PAD_T + plot_h - h:.1f}" '
            f'width="{max(bar_w - 2, 1):.1f}" height="{h:.1f}" fill="{_COLOR_BAR}" rx="1">'
            f"<title>[{b['lower']:.2f}, {b['upper']:.2f}): {b['count']}</title></rect>"
        )
    mid = buckets[n // 2]
    parts.append(
        f'<text x="{_PAD_L + plot_w / 2:.0f}" y="{_CHART_H - 8}" fill="#7d8fa3" '
        f'font-size="10" text-anchor="middle">pnl_vwap ∈ [{buckets[0]["lower"]:.2f}, '
        f'{buckets[-1]["upper"]:.2f}]</text>'
    )
    return _svg_wrap(parts)


def _svg_daily_series(series: list[dict[str, Any]]) -> str:
    """按日双折线：加权 pnl_vwap + 平均 par_rate（各自归一到独立 y 轴）。"""
    if not series:
        return _empty_hint("无按日数据")
    labels = [s["date"][4:] for s in series]  # MMDD
    lines = [
        ([s["weighted_pnl_vwap"] for s in series], _COLOR_LINE1, "加权 pnl_vwap"),
        ([s["avg_par_rate"] for s in series], _COLOR_LINE2, "平均 par_rate"),
    ]
    parts = [_svg_frame(1.0, "")]
    for values, color, name in lines:
        pts = _line_points(values, len(series))
        legend_y = _PAD_T + 10 + 14 * lines.index((values, color, name))
        if pts:
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8"/>')
        parts.append(
            f'<text x="{_CHART_W - _PAD_R - 130}" y="{legend_y}" fill="{color}" font-size="11">{name}</text>'
        )
    parts.append(_x_axis_labels(labels))
    return _svg_wrap(parts)


def _svg_hbar(rows: list[dict[str, Any]], title: str) -> str:
    """横向条形排行：正(成本)红 / 负(优)绿，零轴按符号自适应定位。

    宽度自适应（width=100% + preserveAspectRatio），与分布/走势图一致。
    """
    if not rows:
        return _empty_hint("无排行数据")
    shown = rows[:10]
    values = [r["weighted_pnl_vwap"] for r in shown]
    valid = [abs(v) for v in values if v is not None]
    max_v = max(valid) if valid else 1.0
    has_neg = any((v or 0) < 0 for v in values)
    has_pos = any((v or 0) > 0 for v in values)
    bar_h, gap = 18, 6
    height = _PAD_T + len(shown) * (bar_h + gap) + 8
    label_w, plot_w = 130, _CHART_W - 130 - 70
    # 零轴位置：正负共存居中；全正靠左；全负靠右
    if has_neg and has_pos:
        zero_x, scale_w = label_w + plot_w / 2, plot_w / 2
    elif has_neg:
        zero_x, scale_w = label_w + plot_w, plot_w
    else:
        zero_x, scale_w = label_w, plot_w
    parts = [f'<h2 style="margin-top:0">{_esc(title)}</h2>',
             f'<svg width="100%" height="{height}" viewBox="0 0 {_CHART_W} {height}" preserveAspectRatio="xMidYMid meet">']
    for i, r in enumerate(shown):
        y = _PAD_T + i * (bar_h + gap)
        v = r["weighted_pnl_vwap"]
        w = (abs(v) / max_v * scale_w) if v is not None else 0
        color = _COLOR_POS if (v or 0) >= 0 else _COLOR_NEG
        x = zero_x if (v or 0) >= 0 else zero_x - w
        label_x, anchor = (x + w + 5, "start") if (v or 0) >= 0 else (x - 5, "end")
        parts.append(
            f'<text x="{label_w - 8}" y="{y + 13}" fill="#9fb3c8" font-size="11" text-anchor="end">'
            f'{_esc(_trunc(r["name"], 16))}</text>'
            f'<rect x="{x:.1f}" y="{y}" width="{max(w, 0.5):.1f}" height="{bar_h}" fill="{color}" rx="2" opacity="0.85"/>'
            f'<text x="{label_x:.1f}" y="{y + 13}" fill="#7d8fa3" font-size="11" text-anchor="{anchor}">{_fmt_num(v)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _svg_pwp_curve(points: list[dict[str, Any]]) -> str:
    """PWP 五档位均值曲线。"""
    valid = [p for p in points if p.get("avg_pwp") is not None]
    if not valid:
        return _empty_hint("无 PWP 数据")
    values = [p["avg_pwp"] for p in points]
    parts = [_svg_frame(1.0, "")]
    pts = _line_points(values, len(points))
    if pts:
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{_COLOR_LINE1}" stroke-width="2"/>')
    for i, p in enumerate(points):
        x, y = _point_xy(i, p.get("avg_pwp"), values, len(points))
        if x is None:
            continue
        parts.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{_COLOR_LINE1}"/>'
            f'<text x="{x:.1f}" y="{y - 10:.1f}" fill="#9fb3c8" font-size="10" text-anchor="middle">'
            f'{_fmt_num(p.get("avg_pwp"))}</text>'
            f'<text x="{x:.1f}" y="{_CHART_H - 8}" fill="#7d8fa3" font-size="10" text-anchor="middle">'
            f'{p["rate"]}%</text>'
        )
    return _svg_wrap(parts)


# ═══════════════════════════════════════════════════════════════════════════
# 覆盖率表与缺口附录
# ═══════════════════════════════════════════════════════════════════════════


def _render_coverage_table(coverage: Optional[dict[str, Any]]) -> str:
    """日期 × 指标覆盖率表（单元格按覆盖率着色，BDIB 依赖指标带 * 标记）。"""
    if not coverage or not coverage.get("rows"):
        return ""
    metrics = coverage["metrics"]
    dependent = set(coverage.get("bdib_dependent_metrics") or [])
    header = "".join(
        f"<th>{m}{'*' if m in dependent else ''}</th>" for m in metrics
    )
    body_rows = []
    for row in coverage["rows"]:
        cells = "".join(_coverage_cell(row["coverage"].get(m)) for m in metrics)
        body_rows.append(
            f'<tr><td class="l">{_esc(row["date"])}</td>'
            f"<td>{row['total_routes']}</td>{cells}</tr>"
        )
    return f"""
<h2>指标覆盖率（%）<span style="font-size:11px;color:#5f7186">　* = 依赖 BDIB 行情</span></h2>
<div class="panel" style="overflow-x:auto;max-height:420px;overflow-y:auto">
<table><thead><tr><th class="l">日期</th><th>routes</th>{header}</tr></thead>
<tbody>{''.join(body_rows)}</tbody></table></div>"""


def _render_health_appendix(health: Optional[dict[str, Any]]) -> str:
    """BDIB 缺口附录：仅列出非 ok 日期。"""
    if not health or not health.get("dates"):
        return ""
    gap_dates = [d for d in health["dates"] if d["status"] != "ok"]
    if not gap_dates:
        return '<h2>BDIB 缺口附录</h2><div class="panel">监控范围内 BDIB 覆盖完整，无缺口。</div>'
    rows = "".join(
        f'<tr><td class="l">{d["date"]}</td>'
        f'<td><span class="tag tag-{d["status"]}">{d["status"]}</span></td>'
        f"<td>{d['coverage_pct']:.1f}%</td><td>{d['missing_ticker_count']}</td>"
        f"<td>{d['retention_days_left']}</td>"
        f'<td class="l" style="white-space:normal">{_esc(", ".join(d["missing_tickers"][:8]))}'
        f'{"…" if d["missing_ticker_count"] > 8 else ""}</td></tr>'
        for d in gap_dates
    )
    return f"""
<h2>BDIB 缺口附录（{len(gap_dates)} 天）</h2>
<div class="panel" style="overflow-x:auto">
<table><thead><tr><th class="l">日期</th><th>状态</th><th>覆盖率</th>
<th>缺口 ticker</th><th>保留窗口剩余(天)</th><th class="l">缺失 ticker 样例</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="meta" style="margin-top:8px">保留窗口内（partial/missing）可用 scripts/ops/backfill_bdib_by_market.py 回补；unrecoverable 已超出 Bloomberg BDIB 保留期限，无法回补。</div>
</div>"""


# ═══════════════════════════════════════════════════════════════════════════
# SVG 基础件
# ═══════════════════════════════════════════════════════════════════════════


def _svg_frame(max_val: float, ylabel: str) -> str:
    """坐标框架：左边轴 + 底部轴线。"""
    plot_h = _CHART_H - _PAD_T - _PAD_B
    return (
        f'<line x1="{_PAD_L}" y1="{_PAD_T}" x2="{_PAD_L}" y2="{_PAD_T + plot_h}" stroke="#2a3648"/>'
        f'<line x1="{_PAD_L}" y1="{_PAD_T + plot_h}" x2="{_CHART_W - _PAD_R}" y2="{_PAD_T + plot_h}" stroke="#2a3648"/>'
    )


def _line_points(values: list[Optional[float]], count: int) -> str:
    """折线 points 字符串，自动按非 None 值域缩放。"""
    valid = [v for v in values if v is not None]
    if not valid:
        return ""
    pts = []
    for i, v in enumerate(values):
        x, y = _point_xy(i, v, values, count)
        if x is not None:
            pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _point_xy(
    i: int, value: Optional[float], values: list[Optional[float]], count: int,
) -> tuple[Optional[float], Optional[float]]:
    """单点坐标：x 均分，y 按值域线性映射。"""
    if value is None:
        return None, None
    valid = [v for v in values if v is not None]
    lo, hi = min(valid), max(valid)
    span = (hi - lo) or 1.0
    plot_w = _CHART_W - _PAD_L - _PAD_R
    plot_h = _CHART_H - _PAD_T - _PAD_B
    x = _PAD_L + (i + 0.5) * plot_w / max(count, 1)
    y = _PAD_T + plot_h - (value - lo) / span * plot_h
    return x, y


def _x_axis_labels(labels: list[str]) -> str:
    """底部日期标签（稀疏抽稀，最多 8 个）。"""
    if not labels:
        return ""
    step = max(1, len(labels) // 8)
    plot_w = _CHART_W - _PAD_L - _PAD_R
    parts = []
    for i in range(0, len(labels), step):
        x = _PAD_L + (i + 0.5) * plot_w / len(labels)
        parts.append(
            f'<text x="{x:.0f}" y="{_CHART_H - 8}" fill="#7d8fa3" font-size="10" '
            f'text-anchor="middle">{_esc(labels[i])}</text>'
        )
    return "".join(parts)


def _svg_wrap(parts: list[str]) -> str:
    return f'<svg width="100%" height="{_CHART_H}" viewBox="0 0 {_CHART_W} {_CHART_H}" preserveAspectRatio="xMidYMid meet">{"".join(parts)}</svg>'


def _coverage_cell(pct: Optional[float]) -> str:
    """覆盖率单元格：按数值渐变着色。"""
    if pct is None:
        return '<td style="color:#5f7186">-</td>'
    if pct >= 99.0:
        bg = "#1b3a2f"
    elif pct >= 90.0:
        bg = "#2c3a1c"
    elif pct >= 50.0:
        bg = "#3a3418"
    else:
        bg = "#3a1f1f"
    return f'<td style="background:{bg}">{pct:.1f}</td>'


def _empty_hint(text: str) -> str:
    return f'<div style="color:#5f7186;font-size:12px;padding:24px;text-align:center">{_esc(text)}</div>'


# ═══════════════════════════════════════════════════════════════════════════
# 格式化工具
# ═══════════════════════════════════════════════════════════════════════════


def _fmt_num(value: Optional[float], digits: int = 2) -> str:
    """数值格式化，None → '-'。"""
    if value is None:
        return "-"
    return f"{value:,.{digits}f}"


def _fmt_big(value: Optional[float]) -> str:
    """大数值缩写（K/M/B）。"""
    if value is None:
        return "-"
    abs_v = abs(value)
    if abs_v >= 1e9:
        return f"{value / 1e9:.2f}B"
    if abs_v >= 1e6:
        return f"{value / 1e6:.2f}M"
    if abs_v >= 1e3:
        return f"{value / 1e3:.1f}K"
    return f"{value:.0f}"


def _fx_coverage_sub(kpi: dict[str, Any]) -> str:
    """总成交金额卡片的副标题：fx_rate 覆盖率提示。"""
    coverage = kpi.get("fx_coverage")
    if coverage is None:
        return "USD 换算 · 无 fx_rate 数据"
    pct = coverage * 100.0
    if pct >= 99.0:
        return "USD 换算 · fx_rate 全覆盖"
    return f"USD 换算 · fx_rate 覆盖率 {pct:.0f}%"


def _fmt_risk(stddev: Optional[float], cvar: Optional[float]) -> str:
    """风险卡片：stddev / CVaR 合并展示。"""
    if stddev is None and cvar is None:
        return "-"
    s = "-" if stddev is None else f"{stddev:.2f}"
    c = "-" if cvar is None else f"{cvar:.2f}"
    return f"{s} / {c}"


def _fmt_pct(value: Optional[float]) -> str:
    """百分比展示（0-1 小数 → %，None → '-'）。"""
    if value is None:
        return "-"
    return f"{value * 100.0:.1f}%"


def _fmt_duration(seconds: Optional[float]) -> str:
    """历时展示：秒 → 分钟/小时。"""
    if seconds is None:
        return "-"
    if seconds >= 3600:
        return f"{seconds / 3600:.1f}h"
    if seconds >= 60:
        return f"{seconds / 60:.1f}m"
    return f"{seconds:.0f}s"


def _trunc(text: str, max_len: int) -> str:
    """长文本截断。"""
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _css_id(text: Any) -> str:
    """转义为 CSS 标识符安全的 id（仅保留字母数字与 -_，其余转义）。"""
    return "".join(c if c.isalnum() or c in "-_" else f"-{ord(c):x}" for c in str(text))


def _esc(text: Any) -> str:
    """HTML 转义。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
