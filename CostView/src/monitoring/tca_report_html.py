"""TCA 独立 HTML 报告渲染器 — 纯 Python 生成自包含静态 HTML。

零外部依赖：内联 CSS + 服务端生成 SVG 图表（无 JS），
浏览器直接打开即可查看，可邮件分发、离线归档。

报告结构：
    报告头（标题/生成时间/过滤条件/口径脚注） → KPI 卡片 → 数据质量提示 →
    pnl_vwap 直方图 + 按日走势 → broker/algo 排行 + PWP 曲线 →
    市场冲击分解表 → 异常路由明细表 → 指标覆盖率表 → BDIB 缺口附录 → 页脚

口径脚注由 ``report_spec.REPORT_SPEC`` 生成（单一真相源，避免文档-实现漂移）。
"""

from __future__ import annotations

from typing import Any, Optional

from data_access.config import Config

from . import report_measure as rm
from .report_spec import REPORT_SPEC, footer_text

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
                          report.get("anomaly"), report.get("weight_coverage")),
        _render_data_quality(report, health),
        _render_market_charts(report),
        _render_charts(report),
        _render_impact_breakdown(report.get("impact_breakdown"),
                                 report.get("weight_coverage")),
        _render_anomaly_table(report.get("anomaly")),
        _render_coverage_table(report.get("metric_coverage"), _gap_dates(health),
                               _tca_gap_dates(health)),
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
/* 可滚动明细面板：自身作为滚动容器，去掉内边距避免 sticky 表头与内容上沿留缝；
   表头sticky于面板顶部，未成交记录滚动时沉入表头之下而非穿过。 */
.scroll-panel {{ background: #1a2332; border: 1px solid #2a3648; border-radius: 8px; padding: 0; margin-top: 12px; max-height: 520px; overflow: auto; }}
.scroll-panel > table {{ margin: 0; }}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
@media (max-width: 1100px) {{ .grid2 {{ grid-template-columns: 1fr; }} }}
table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 12px; }}
th, td {{ padding: 5px 8px; text-align: right; border-bottom: 1px solid #22304a; white-space: nowrap; }}
/* 表头吸顶：不透明背景 + 更高层级 + 实底边框，确保滚动时记录沉入表头之下 */
th {{ color: #7d8fa3; font-weight: 600; position: sticky; top: 0; z-index: 3; background: #202b3d; border-bottom: 2px solid #2a3648; background-clip: padding-box; }}
td.l, th.l {{ text-align: left; }}
.warn {{ background: #3a2a1a; border: 1px solid #8a5a2a; border-radius: 8px; padding: 12px 16px; margin-top: 12px; color: #ffb74d; font-size: 13px; }}
.tag {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }}
.tag-ok {{ background: #1b3a2f; color: #26a69a; }}
.tag-partial {{ background: #3a3418; color: #ffca28; }}
.tag-missing {{ background: #3a1f1f; color: #ef5350; }}
.tag-unrecoverable {{ background: #2a2f38; color: #90a4ae; }}
.tag-alert {{ background: #3a1f1f; color: #ef5350; }}
.tag-sev-critical {{ background: #3a1f1f; color: #ef5350; }}
.tag-sev-warning {{ background: #3a3418; color: #ffca28; }}
.tag-overfill {{ background: #4a1f1f; color: #ff8a80; margin-left: 4px; }}
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
    """报告头：标题 + 过滤条件摘要（含作用域 / preset / 数据截至日）+ 口径脚注。"""
    cond = [f"日期 {filters.get('start_date')} ~ {filters.get('end_date')}"]
    scope = filters.get("scope") or {}
    if scope.get("label"):
        cond.append(f"统计范围 {scope['label']}（全报告统一口径）")
    if filters.get("preset"):
        cond.append(f"口径 last={filters['preset']}")
    if filters.get("as_of_date"):
        cond.append(f"数据截至 {filters['as_of_date']}")
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
{_scope_note(scope)}<div class="disclaimer">{_esc(footer_text())}</div>"""


def _scope_note(scope: dict[str, Any]) -> str:
    """作用域告警：用户把白名单外市场纳入报告时显式提示（不静默混入分母）。

    白名单外市场（CN/BZ 等）本就不拉 BDIB 行情，其 BDIB 依赖指标必然为 NULL；
    混入后覆盖率与走势会被天然缺数据稀释，读者须知道该情形来自口径而非数据缺陷。
    """
    outside = scope.get("out_of_scope") or []
    if not outside:
        return ""
    return (
        '<div class="warn">所选市场 ' + _esc(", ".join(outside))
        + " 不在 BDIB 白名单内 —— 这些市场不拉取 BDIB 行情，其 BDIB 依赖指标必然为 "
        "NULL，覆盖率与走势请对照下方覆盖率表解读。</div>"
    )


def _render_footer() -> str:
    """页脚：口径脚注（与报告头同源，由 REPORT_SPEC 生成）+ 数据源。"""
    return (
        '<div class="footer">'
        "EMSXView CostView · 数据源 tca_route_summary / fill_bdib / raw_bdib · "
        f"{_esc(footer_text())}"
        "</div>"
    )


def _render_market_tabs(
    markets: Optional[list[dict[str, Any]]],
    kpi: Optional[dict[str, Any]],
) -> str:
    """市场概览（007）：市场由 Config.MARKET_ORDER 设定顺序。

    始终展示全部市场汇总表（route 数 + 成交金额 USD），不再提供点击市场
    筛选概览范围的交互（取消点击市场筛选概览范围的功能）。
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
    if not ordered:
        return ""
    return f"""
<h2>市场概览</h2>
{_market_summary_table(ordered)}"""


def _market_summary_table(markets: list[dict[str, Any]]) -> str:
    """市场汇总表：route 数 + 成交金额（本币 / USD）。"""
    rows = "".join(
        f'<tr><td class="l">{_esc(Config.MARKET_ORDER.get(m["exchange"], m["exchange"]))}</td>'
        f'<td class="l">{_esc(m["exchange"])}</td>'
        f"<td>{m['route_count']:,}</td>"
        f"<td>{_fmt_big(m.get('notional'))}</td>"
        f"<td>{_fmt_big(m.get('notional_usd'))}</td></tr>"
        for m in markets
    )
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
    weight_coverage: Optional[dict[str, Any]] = None,
) -> str:
    """KPI 卡片区：整体水位（6）+ 基准/短缺/风险/完成率/异常（7）。"""
    if not kpi:
        return '<div class="warn">tca_route_summary 无数据 — 请先运行管道 S5.5。</div>'
    cards = _kpi_card_specs(kpi, extra, weight_coverage)
    if anomaly is not None:
        cards.append(
            ("异常路由", f"{anomaly.get('count', 0):,}", "见下方明细"),
        )
    inner = "".join(
        f'<div class="card"><div class="label">{_esc(label)}</div>'
        f'<div class="value">{_esc(value)}</div>'
        f'<div class="sub">{_esc(sub)}</div></div>'
        for label, value, sub in cards
    )
    return f'<div class="cards">{inner}</div>'


def _kpi_card_specs(
    kpi: dict[str, Any],
    extra: Optional[dict[str, Any]],
    weight_coverage: Optional[dict[str, Any]],
) -> list[tuple[str, str, str]]:
    """KPI 卡片 (标签, 数值, 副标题) 清单；加权指标副标题附样本量与权重覆盖率。"""
    metrics = (weight_coverage or {}).get("metrics") or {}

    def note(metric: str) -> str:
        return _weight_note(metrics.get(metric))

    cards = [
        ("Route 总数", f"{kpi['route_count']:,}", ""),
        ("总成交股数", _fmt_big(kpi["total_route_shares"]), "RouteShares 合计"),
        # 007: 总成交金额（USD 换算，标注 fx_rate 覆盖率）
        ("总成交金额（美元）", _fmt_big(kpi.get("notional_usd")), _fx_coverage_sub(kpi)),
        ("加权 pnl_vwap", _fmt_num(kpi.get("weighted_pnl_vwap")),
         "成交额加权 · VWAP 基准" + note("pnl_vwap")),
        ("平均 par_rate", _fmt_num(kpi.get("avg_par_rate")),
         "成交额加权" + note("par_rate")),
        ("平均 RPM", _fmt_num(kpi.get("avg_rpm")), "成交额加权" + note("RPM")),
    ]
    if not extra:
        return cards
    return cards + [
        ("加权 arrival 成本", _fmt_num(extra.get("arrival_cost_bps")),
         "决策基准 · 成交额加权" + note("arrival_cost_bps")),
        ("加权 IS (bps)", _fmt_num(extra.get("wagner_is_bps")),
         "实现短缺 · 成交额加权" + note("wagner_is_bps")),
        ("成本风险 stddev/CVaR",
         _fmt_risk(extra.get("cost_stddev"), extra.get("cost_cvar")),
         "尾部风险" + note("cost_cvar")),
        ("组合完成率", _fmt_pct(extra.get("avg_fill")), "Σfill / ΣRouteShares"),
        ("未成交金额缺口(USD)", _fmt_big(extra.get("unfilled_notional_usd")),
         _unfilled_sub(extra)),
        # 完全未执行（零成交）单独成卡：此前仅 avg_fill 分母隐含其存在，
        # 成本 KPI 与异常清单都看不到这批路由。
        ("零成交路由", f"{extra.get('zero_fill_routes', 0):,}",
         f"委托金额 {_fmt_big(extra.get('zero_fill_notional_usd'))} · 完全未执行"),
    ]


def _unfilled_sub(extra: dict[str, Any]) -> str:
    """未成交金额缺口卡副标题：价格回退口径 + 未能计价路由数（缺口低估规模）。"""
    text = "Σ(未成交 × 价格回退链 × 汇率)"
    unpriced = extra.get("unfilled_notional_unpriced_routes")
    if unpriced:
        text += f"　未计价 {int(unpriced):,} 条（未计入）"
    return text


def _render_data_quality(
    report: dict[str, Any],
    health: Optional[dict[str, Any]] = None,
) -> str:
    """数据质量提示区：overfill / 订单参与率 >100% / TCA 整日缺失。

    数据质量计数取自覆盖率服务的一致性探针（覆盖全部路由，不受异常明细截断
    影响）；TCA 整日缺失取自健康扫描的差集检测（有成交但无 TCA 汇总的日期），
    使 ETL 断档在报告内可见 —— 该日前覆盖率表同样源自 tca_route_summary，
    无差集检测时对断档全体失明。无任何信号时不渲染该区。
    """
    parts: list[str] = []
    consistency = (report.get("metric_coverage") or {}).get("consistency") or {}
    overfill = consistency.get("overfill_routes") or 0
    gt100 = consistency.get("order_par_gt100_orders") or 0
    if overfill or gt100:
        completion_pct = _fmt_pct_raw(consistency.get("completion_consistency_pct"))
        order_pct = _fmt_pct_raw(consistency.get("order_par_consistency_pct"))
        parts.append(
            f'<div class="warn">成交超过委托（fill &gt; RouteShares）的路由 {overfill} 条'
            f"（完成率一致性 {completion_pct}）；订单参与率求和 &gt;100% 的订单 {gt100} 个"
            f"（一致性 {order_pct}）。上述为数据矛盾信号，建议核对上游成交/委托数据。</div>"
        )
    tca_gap = sorted((health or {}).get("tca_gap_dates") or [])
    if tca_gap:
        sample = ", ".join(tca_gap[:10]) + ("…" if len(tca_gap) > 10 else "")
        parts.append(
            f'<div class="warn">区间内 {len(tca_gap)} 个交易日有成交记录但无 TCA 汇总'
            f"（管道 S5.5 未产出）：{_esc(sample)} —— 走势/覆盖率在这些日期的缺失属"
            "管道缺口，并非非交易日，请先回补 TCA 汇总再解读趋势。</div>"
        )
    if not parts:
        return ""
    return "<h2>数据质量提示</h2>\n" + "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# 图表区
# ═══════════════════════════════════════════════════════════════════════════


def _render_charts(report: dict[str, Any]) -> str:
    """四个图表面板：直方图 / 按日走势 / 排行 / PWP 曲线。"""
    histogram = _svg_histogram(report.get("pnl_vwap_histogram"))
    daily_series = report.get("daily_series") or []
    daily = _svg_daily_series(daily_series)
    broker = _svg_hbar(report.get("rankings", {}).get("by_broker") or [], "Broker 排行（加权 pnl_vwap）")
    algo = _svg_hbar(report.get("rankings", {}).get("by_algo") or [], "Algo 排行（加权 pnl_vwap）")
    pwp = _svg_pwp_curve(report.get("pwp_curve") or [])
    daily_note = _daily_coverage_note(len(daily_series))
    return f"""
<h2>分布与走势</h2>
<div class="grid2">
  <div class="panel"><h2 style="margin-top:0">pnl_vwap 分布直方图</h2>{histogram}</div>
  <div class="panel"><h2 style="margin-top:0">按日加权 pnl_vwap / 平均 par_rate</h2>{daily}{daily_note}</div>
</div>
<h2>执行方排行</h2>
<div class="grid2">
  <div class="panel">{broker}</div>
  <div class="panel">{algo}</div>
</div>
<h2>PWP 分档均值</h2>
<div class="panel">{pwp}</div>"""


def _daily_coverage_note(covered_days: int) -> str:
    """按日走势覆盖度提示（014）。

    走势仅含 tca_route_summary 中有数据的交易日；不补零 —— 0 表示「成本为零」，
    把无数据日补成 0 属数据失真。缺失定位交由覆盖率表与 BDIB 缺口附录交叉核对。
    """
    if covered_days <= 0:
        return ""
    return (
        f'<div class="meta">走势含 {covered_days} 个有数据交易日；区间内无记录的日期'
        "（非交易日或 TCA 数据缺失，后者已由整日缺失检测自动识别、见数据质量提示）"
        "请对照下方覆盖率表与 BDIB 缺口附录。</div>"
    )


def _render_market_charts(report: dict[str, Any]) -> str:
    """分市场成交金额（美元）排名 + 每日趋势（与 Report 页面双向对齐）。

    排名：按 notional_usd 降序竖向柱形；趋势：累计成交额 Top 10 市场多折线。
    """
    ranking = _svg_market_ranking(report.get("market_notional_ranking") or [])
    trend = _svg_market_trend(report.get("market_notional_trend") or [])
    return f"""
<h2>分市场成交金额（美元）</h2>
<div class="grid2">
  <div class="panel"><h2 style="margin-top:0">按市场的成交金额（美元）排名</h2>{ranking}</div>
  <div class="panel"><h2 style="margin-top:0">按市场的成交金额（美元）每日趋势（Top {_TOP_TREND_MARKETS}）</h2>{trend}</div>
</div>"""


def _svg_market_ranking(rows: list[dict[str, Any]]) -> str:
    """按市场成交金额（美元）排名竖向柱形（notional_usd 降序）。"""
    shown = [r for r in rows if r.get("notional_usd") is not None]
    if not shown:
        return _empty_hint("无市场成交金额数据")
    max_v = max((r["notional_usd"] for r in shown), default=1.0) or 1.0
    n = len(shown)
    plot_w = _CHART_W - _PAD_L - _PAD_R
    plot_h = _CHART_H - _PAD_T - _PAD_B
    bar_w = plot_w / max(n, 1)
    parts = [_svg_frame(max_v, "")]
    for i, r in enumerate(shown):
        h = r["notional_usd"] / max_v * plot_h
        x = _PAD_L + i * bar_w
        label = r.get("name") or r.get("exchange") or ""
        parts.append(
            f'<rect x="{x + 1:.1f}" y="{_PAD_T + plot_h - h:.1f}" '
            f'width="{max(bar_w - 2, 1):.1f}" height="{h:.1f}" fill="{_COLOR_BAR}" rx="1">'
            f'<title>{_esc(str(label))}: {_fmt_big(r["notional_usd"])}</title></rect>'
        )
        parts.append(
            f'<text x="{x + bar_w / 2:.0f}" y="{_CHART_H - 8}" fill="#7d8fa3" '
            f'font-size="9" text-anchor="middle">{_esc(_trunc(str(label), 8))}</text>'
        )
    return _svg_wrap(parts)


#: 市场趋势 Top 市场数
_TOP_TREND_MARKETS = 10

#: 多折线调色板（与 Report 页面一致）
_MARKET_TREND_PALETTE = [
    "#4fc3f7", "#ffb74d", "#26a69a", "#ab47bc", "#ef5350",
    "#ffca28", "#66bb6a", "#5c6bc0", "#ec407a", "#8d6e63",
]


def _svg_market_trend(points: list[dict[str, Any]]) -> str:
    """按市场成交金额（美元）每日趋势（Top 10 市场多折线，共享 y 轴）。"""
    if not points:
        return _empty_hint("无市场趋势数据")
    total: dict[str, float] = {}
    for p in points:
        total[p["exchange"]] = total.get(p["exchange"], 0.0) + (p.get("notional_usd") or 0.0)
    top_ex = [e for e, _ in sorted(total.items(), key=lambda kv: kv[1], reverse=True)[:_TOP_TREND_MARKETS]]
    by_date: dict[str, dict[str, float]] = {}
    order: list[str] = []
    for p in points:
        if p["exchange"] not in top_ex:
            continue
        d = p["date"]
        by_date.setdefault(d, {})[p["exchange"]] = p.get("notional_usd") or 0.0
        if d not in order:
            order.append(d)
    order.sort()
    if not order:
        return _empty_hint("无市场趋势数据")
    all_vals = [by_date[d].get(ex) for ex in top_ex for d in order if by_date[d].get(ex) is not None]
    if not all_vals:
        return _empty_hint("无市场趋势数据")
    lo, hi = min(all_vals), max(all_vals)
    span = (hi - lo) or 1.0
    plot_w = _CHART_W - _PAD_L - _PAD_R
    plot_h = _CHART_H - _PAD_T - _PAD_B

    def _xy(i: int, v: float) -> tuple[float, float]:
        x = _PAD_L + (i + 0.5) * plot_w / max(len(order), 1)
        y = _PAD_T + plot_h - (v - lo) / span * plot_h
        return x, y

    parts = [_svg_frame(1.0, "")]
    for ei, ex in enumerate(top_ex):
        coords = []
        for i, d in enumerate(order):
            v = by_date[d].get(ex)
            if v is None:
                continue
            x, y = _xy(i, v)
            coords.append(f"{x:.1f},{y:.1f}")
        color = _MARKET_TREND_PALETTE[ei % len(_MARKET_TREND_PALETTE)]
        if coords:
            parts.append(f'<polyline points="{" ".join(coords)}" fill="none" stroke="{color}" stroke-width="1.8"/>')
        parts.append(
            f'<text x="{_PAD_L + 4}" y="{_PAD_T + 12 + ei * 13}" fill="{color}" '
            f'font-size="10">{_esc(ex)}</text>'
        )
    parts.append(_x_axis_labels([d[4:] for d in order]))
    return _svg_wrap(parts)


def _render_impact_breakdown(
    impact: Optional[dict[str, Any]],
    weight_coverage: Optional[dict[str, Any]] = None,
) -> str:
    """市场冲击分解表（B2-2）：暂时冲击 5/10/30min + 永久冲击 + 样本/权重覆盖。"""
    if not impact:
        return ""
    metrics = (weight_coverage or {}).get("metrics") or {}
    rows = [
        ("暂时冲击 5min", _fmt_num(impact.get("temp_impact_5min_bps")),
         "成交后 5 分钟价格恢复偏离", "temp_impact_5min_bps"),
        ("暂时冲击 10min", _fmt_num(impact.get("temp_impact_10min_bps")),
         "成交后 10 分钟价格恢复偏离", "temp_impact_10min_bps"),
        ("暂时冲击 30min", _fmt_num(impact.get("temp_impact_30min_bps")),
         "成交后 30 分钟价格恢复偏离", "temp_impact_30min_bps"),
        ("永久冲击", _fmt_num(impact.get("perm_impact_bps")),
         "收盘价相对到达价的持续偏离", "perm_impact_bps"),
        ("收盘价成本", _fmt_num(impact.get("close_cost_bps")),
         "收盘价基准偏离", "close_cost_bps"),
    ]
    body = "".join(
        f'<tr><td class="l">{_esc(label)}</td><td>{_esc(value)} bps</td>'
        f'<td class="l" style="white-space:normal">'
        f"{_esc(desc + _weight_note(metrics.get(metric)))}</td></tr>"
        for label, value, desc, metric in rows
    )
    truncated_count = impact.get("recovery_truncated_count")
    share = impact.get("recovery_truncated_share")
    truncated_note = ""
    if truncated_count:
        pct = f"{share * 100:.1f}%" if share is not None else "-"
        truncated_note = (
            f"其中 {truncated_count:,} 条（{pct}）因恢复窗口越界使用次日收盘价，"
            "冲击值为跨日兜底口径。"
        )
    return f"""
<h2>市场冲击分解</h2>
<div class="panel" style="overflow-x:auto">
<table><thead><tr><th class="l">冲击维度</th><th>加权值</th><th class="l">说明</th></tr></thead>
<tbody>{body}</tbody></table>
<div class="meta" style="margin-top:8px">成交额加权（fill × p_avg，与总成交金额同源）；恢复窗口越界时使用次日收盘价作跨日恢复价格。{_esc(truncated_note)}</div>
</div>"""


#: 异常明细表渲染上限（与 REPORT_SPEC 同源；超出的路由不展开 HTML，仅保留计数）
_MAX_ANOMALY_ROWS_RENDERED = int(REPORT_SPEC["anomaly_row_limit"])


def _render_anomaly_table(anomaly: Optional[dict[str, Any]]) -> str:
    """异常路由明细表（S6）：命中阈值规则的路由逐单清单。

    HTML 渲染上限 ``_MAX_ANOMALY_ROWS_RENDERED`` 条；明细由后端按「严重度优先」
    排序后返回，故渲染的即为最严重的 N 条（截断样本无偏）。其余条数仅计数提示，
    全量明细经 ``export_ref`` 指向的 CSV 获取，避免数千行撑大 HTML（上季度曾达
    8500+ 行、报告 5MB+，浏览器渲染与导出显著变慢）。
    """
    if anomaly is None:
        return ""
    rows = anomaly.get("rows") or []
    count = anomaly.get("count", len(rows))
    if not rows:
        return f"""
<h2>异常路由明细</h2>
<div class="panel">本期无异常路由（{_esc(str(count))} 条触发阈值）。</div>"""
    rendered = rows[:_MAX_ANOMALY_ROWS_RENDERED]
    # count 为全量命中数；rows 可能已被后端 limit 截断，故截断量以 count 为基准
    truncated = max(0, count - len(rendered))
    body_rows = []
    for r in rendered:
        hits = r.get("hits") or []
        tags = "".join(
            f'<span class="tag {_severity_tag_class(h.get("severity"))}">'
            f"{_esc(_fmt_hit(h))}</span>"
            for h in hits
        )
        body_rows.append(
            f'<tr>'
            f'<td class="l" style="white-space:normal">{tags}</td>'
            f'<td class="l">{_esc(r.get("date", ""))}</td>'
            f'<td class="l">{_esc(r.get("order_id", ""))}</td>'
            f'<td class="l">{_esc(r.get("route_id", ""))}</td>'
            f'<td class="l">{_esc(r.get("ticker", ""))}</td>'
            f'<td class="l">{_esc(r.get("exchange") or "")}</td>'
            f'<td class="l">{_esc(r.get("side") or "")}</td>'
            f'<td class="l">{_fmt_money(r.get("notional_local"), r.get("currency"))}</td>'
            f'<td class="l">{_fmt_money(r.get("notional_usd"), "USD")}</td>'
            f'<td class="l">{_esc(r.get("broker") or "")}</td>'
            f'<td class="l">{_esc(r.get("algo") or "")}</td>'
            f'<td>{_fmt_overfill_cell(r.get("completion_rate"), bool(r.get("overfill")))}</td>'
            f'<td>{_fmt_pct(r.get("par_rate"))}</td>'
            f'<td>{_fmt_order_par_rate(r.get("order_par_rate"), bool(r.get("order_par_gt100")))}</td>'
            f'<td>{_fmt_int(r.get("fill_count"))}</td>'
            f'<td>{_fmt_big(r.get("route_shares"))}</td>'
            f'<td>{_fmt_big(r.get("fill"))}</td>'
            f'<td>{_fmt_num(r.get("pnl_vwap"))}</td>'
            f'<td>{_fmt_num(r.get("arrival_cost_bps"))}</td>'
            f'<td>{_fmt_num(r.get("wagner_is_bps"))}</td>'
            f'<td>{_fmt_num(r.get("opportunity_cost"))}</td>'
            f'<td>{_fmt_big(r.get("unfilled"))}</td>'
            f'<td>{_fmt_num(r.get("cost_cvar"))}</td>'
            f'<td>{_fmt_duration(r.get("order_duration_sec"))}</td>'
            f'<td>{_esc("1" if r.get("recovery_truncated") else "")}</td>'
            f'</tr>'
        )
    return f"""
<h2>异常路由明细（{_esc(str(count))} 条）</h2>
{_anomaly_notes(len(rendered), truncated, anomaly.get("export_ref"))}
<div class="scroll-panel">
<table><thead><tr>
<th class="l">命中规则</th><th class="l">日期</th><th class="l">订单</th><th class="l">路由</th>
<th class="l">标的</th><th class="l">交易所</th><th class="l">方向</th><th class="l">成交金额(本币)</th><th class="l">成交金额(USD)</th>
<th class="l">Broker</th><th class="l">Algo</th><th>完成率</th><th>路由参与率</th><th>订单参与率</th><th>填充笔数</th><th>路由股数</th><th>成交股数</th><th>pnl_vwap</th>
<th>arrival</th><th>IS</th><th>机会成本</th><th>未成交</th><th>CVaR</th>
<th>历时</th><th>跨日</th>
</tr></thead><tbody>{''.join(body_rows)}</tbody></table></div>"""


def _severity_tag_class(severity: Optional[str]) -> str:
    """命中规则标签的严重度配色：critical 红 / warning 橙。"""
    return "tag-sev-critical" if severity == "critical" else "tag-sev-warning"


def _anomaly_notes(rendered: int, truncated: int, export_ref: Optional[str]) -> str:
    """异常明细的截断说明与全量导出链接。"""
    parts: list[str] = []
    if truncated > 0:
        parts.append(
            f'<div class="warn">已按严重度降序（critical 优先）渲染最严重的前 '
            f"{rendered} 条异常路由；其余 {truncated} 条未在 HTML 中展开，"
            f"已计入上方「异常路由」KPI 计数，可缩小时间范围或收紧阈值查看。</div>"
        )
    if export_ref:
        parts.append(
            f'<div class="meta">全量明细导出：<a href="{_esc(export_ref)}" '
            f'download>{_esc(export_ref)}</a></div>'
        )
    return "".join(parts)


#: 样本覆盖率低于该阈值时提示「样本不足，结论仅供参考」（唯一真相源：report_measure）
_SAMPLE_COVERAGE_MIN_PCT = rm.SAMPLE_COVERAGE_MIN_PCT


def _weight_note(entry: Optional[dict[str, Any]]) -> str:
    """加权 KPI 的样本量与权重覆盖率后缀（全角空格分隔，内联于卡片副标题）。

    条数覆盖与权重覆盖必须并列披露：BDIB 缺口集中在少数大单时，条数覆盖可以很高
    而权重覆盖很低 —— 此时均值是子样本口径，量级不足以支撑跨期对比结论。
    """
    if not entry:
        return ""
    parts: list[str] = []
    n_used, n_total = entry.get("n_used"), entry.get("n_total")
    if n_used is not None and n_total:
        parts.append(
            f"样本 {n_used:,}/{n_total:,}（{_fmt_pct_raw(entry.get('sample_pct'))}）"
        )
    if entry.get("weight_pct") is not None:
        parts.append(f"权重覆盖 {_fmt_pct_raw(entry.get('weight_pct'))}")
    if entry.get("insufficient"):
        parts.append("样本/权重覆盖不足，结论仅供参考")
    return "".join(f"　{part}" for part in parts)


def _sample_note(n_used: Optional[int], n_total: Optional[int]) -> str:
    """样本量提示：``样本 N/M（xx%）``，覆盖率不足时附警示。"""
    if not n_used or not n_total:
        return ""
    pct = n_used / n_total * 100.0
    note = f"样本 {n_used:,}/{n_total:,}（{pct:.0f}%）"
    if pct < _SAMPLE_COVERAGE_MIN_PCT:
        note += "　样本不足，结论仅供参考"
    return note


def _ranking_sample(row: dict[str, Any]) -> str:
    """排行条目的样本量后缀：``　n=used/total``（无数据时不显示）。"""
    n_used, n_total = row.get("n_used"), row.get("route_count")
    if n_used is None or not n_total:
        return ""
    return f"　n={n_used}/{n_total}"


def _svg_histogram(histogram: Optional[dict[str, Any]]) -> str:
    """pnl_vwap 直方图（纵向柱形）+ 样本量披露。

    分布仅覆盖 pnl_vwap 非 NULL 的路由（BDIB 覆盖子集），图下标注
    「样本 N/M」以免读者误以为分布覆盖全部路由而低估尾部风险。
    """
    histogram = histogram or {}
    buckets = histogram.get("buckets") or []
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
    parts.append(
        f'<text x="{_PAD_L + plot_w / 2:.0f}" y="{_CHART_H - 8}" fill="#7d8fa3" '
        f'font-size="10" text-anchor="middle">pnl_vwap ∈ [{buckets[0]["lower"]:.2f}, '
        f'{buckets[-1]["upper"]:.2f}]</text>'
    )
    note = _sample_note(histogram.get("n_used"), histogram.get("n_total"))
    suffix = f'<div class="meta">{_esc(note)}</div>' if note else ""
    return _svg_wrap(parts) + suffix


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
        # max_v 为 0（全部排名值均为 0）时不做缩放，避免除零
        w = (abs(v) / max_v * scale_w) if (v is not None and max_v > 0) else 0
        color = _COLOR_POS if (v or 0) >= 0 else _COLOR_NEG
        x = zero_x if (v or 0) >= 0 else zero_x - w
        label_x, anchor = (x + w + 5, "start") if (v or 0) >= 0 else (x - 5, "end")
        parts.append(
            f'<text x="{label_w - 8}" y="{y + 13}" fill="#9fb3c8" font-size="11" text-anchor="end">'
            f'{_esc(_trunc(r["name"], 16))}</text>'
            f'<rect x="{x:.1f}" y="{y}" width="{max(w, 0.5):.1f}" height="{bar_h}" fill="{color}" rx="2" opacity="0.85"/>'
            f'<text x="{label_x:.1f}" y="{y + 13}" fill="#7d8fa3" font-size="11" text-anchor="{anchor}">{_fmt_num(v)}{_esc(_ranking_sample(r))}</text>'
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


def _gap_dates(health: Optional[dict[str, Any]]) -> set[str]:
    """BDIB 缺口日期集合（供覆盖率表交叉高亮）；未扫描/无数据时为空。"""
    if not health or health.get("status") == "skipped":
        return set()
    return {
        d["date"] for d in health.get("dates") or [] if d.get("status") != "ok"
    }


def _tca_gap_dates(health: Optional[dict[str, Any]]) -> set[str]:
    """TCA 整日缺失日期集合（有成交但无 TCA 汇总）；检测未执行时为空。"""
    if not health or health.get("status") == "skipped":
        return set()
    return set(health.get("tca_gap_dates") or [])


def _render_coverage_table(
    coverage: Optional[dict[str, Any]],
    gap_dates: Optional[set[str]] = None,
    tca_gap_dates: Optional[set[str]] = None,
) -> str:
    """日期 × 指标覆盖率表（原始 / SLA 双口径 + NULL 原因提示）。

    单元格为「原始 / SLA」组合值：SLA 口径剔除结构内必然 NULL（收盘竞价 /
    单笔成交 / BDIB 缺口路由），避免把结构性 NULL 误判成"数据质量差"；
    tooltip 给出 NULL 原因。``gap_dates``（BDIB 缺口日）整行暗红底色、
    ``tca_gap_dates``（TCA 整日缺失日）整行橙底，便于与缺口附录交叉定位。
    """
    if not coverage or not coverage.get("rows"):
        return ""
    metrics = coverage["metrics"]
    dependent = set(coverage.get("bdib_dependent_metrics") or [])
    reasons = coverage.get("null_reasons") or {}
    expected_null = set(coverage.get("expected_null_metrics") or [])
    gap_dates = gap_dates or set()
    tca_gap_dates = tca_gap_dates or set()
    header = "".join(
        f"<th>{m}{'*' if m in dependent else ''}</th>" for m in metrics
    )
    body_rows = []
    for row in coverage["rows"]:
        sla = row.get("sla_coverage") or {}
        if row["date"] in gap_dates:
            row_style = ' style="background:#2a1f1f"'
        elif row["date"] in tca_gap_dates:
            row_style = ' style="background:#3a2a1a"'
        else:
            row_style = ""
        cells = "".join(
            _coverage_cell(
                row["coverage"].get(m), sla.get(m),
                reasons.get(m), m in expected_null,
            )
            for m in metrics
        )
        body_rows.append(
            f'<tr{row_style}><td class="l">{_esc(row["date"])}</td>'
            f"<td>{row['total_routes']}</td>{cells}</tr>"
        )
    overall = coverage.get("overall") or {}
    overall_note = ""
    if overall.get("coverage") is not None:
        overall_note = (
            f"　整体：原始 {_fmt_pct_raw(overall.get('coverage'))} / "
            f"SLA {_fmt_pct_raw(overall.get('sla_coverage'))}"
        )
    return f"""
<h2>指标覆盖率（%）<span style="font-size:11px;color:#5f7186">　* = 依赖 BDIB 行情；单元格＝原始 / SLA；虚线框＝结构性必然 NULL；暗红行＝BDIB 缺口日；橙底行＝TCA 整日缺失</span></h2>
<div class="panel" style="overflow-x:auto;max-height:420px;overflow-y:auto">
<div class="meta">原始覆盖率分母为全部路由；SLA 覆盖率剔除结构内必然 NULL（收盘竞价 / 零成交 / 单笔成交 / BDIB 缺口路由）；单元格底色按 SLA 口径（SLA 无值时回退原始口径）。{_esc(overall_note)}</div>
<table><thead><tr><th class="l">日期</th><th>routes</th>{header}</tr></thead>
<tbody>{''.join(body_rows)}</tbody></table></div>"""


def _render_health_appendix(health: Optional[dict[str, Any]]) -> str:
    """BDIB 缺口附录：三态（未扫描 / 无缺口 / 有缺口）+ 缺口影响面。

    未扫描（超时/异常）与"无缺口"在渲染上显式区分，避免读者误判为数据健康。
    """
    if not health:
        return ""
    if health.get("status") == "skipped":
        reason = {"timeout": "扫描超时", "error": "扫描失败"}.get(
            health.get("reason") or "", health.get("reason") or "未知原因",
        )
        return (
            '<h2>BDIB 缺口附录</h2><div class="warn">'
            f"本次未完成 BDIB 缺口扫描（{_esc(reason)}），缺口状态未知 —— "
            "如需确认请缩小时间范围后重试。</div>"
        )
    if not health.get("dates"):
        return ""
    gap_dates = [d for d in health["dates"] if d["status"] != "ok"]
    if not gap_dates:
        return '<h2>BDIB 缺口附录</h2><div class="panel">监控范围内 BDIB 覆盖完整，无缺口。</div>'
    rows = "".join(
        f'<tr><td class="l">{d["date"]}</td>'
        f'<td><span class="tag tag-{d["status"]}">{d["status"]}</span>'
        f'{" <span class=\"tag tag-missing\">TCA 缺失</span>" if d.get("tca_missing") else ""}</td>'
        f"<td>{d['coverage_pct']:.1f}%</td><td>{d['missing_ticker_count']}</td>"
        f"<td>{d.get('missing_route_count', 0):,}</td>"
        f"<td>{_fmt_big(d.get('missing_notional'))}</td>"
        f"<td>{d['retention_days_left']}</td>"
        f'<td class="l" style="white-space:normal">{_esc(", ".join(d["missing_tickers"][:8]))}'
        f'{"…" if d["missing_ticker_count"] > 8 else ""}</td></tr>'
        for d in gap_dates
    )
    summary = health.get("summary") or {}
    unconvertible = summary.get("total_missing_notional_unconvertible") or 0.0
    unconvertible_note = (
        f"其中未能换算 USD 的本币金额 {_fmt_big(unconvertible)}（缺口金额或被低估）。"
        if unconvertible else ""
    )
    return f"""
<h2>BDIB 缺口附录（{len(gap_dates)} 天）</h2>
<div class="panel" style="overflow-x:auto">
<table><thead><tr><th class="l">日期</th><th>状态</th><th>覆盖率</th>
<th>缺口 ticker</th><th>受影响 route 数</th><th>缺口成交金额</th>
<th>保留窗口剩余(天)</th><th class="l">缺失 ticker 样例</th></tr></thead>
<tbody>{rows}</tbody></table>
<div class="meta" style="margin-top:8px">缺口影响面：合计受影响 route {summary.get('total_missing_routes', 0):,} 条、成交金额 {_fmt_big(summary.get('total_missing_notional'))}（USD 换算与 KPI 同源：fill_bdib 回填 + 小计价单位修正；逐行换算，缺汇率的路由不计入）。{unconvertible_note}标记「TCA 缺失」的日期同时无 TCA 汇总（见数据质量提示）。保留窗口内（partial/missing）可用 scripts/ops/backfill_bdib_by_market.py 回补；unrecoverable 已超出 Bloomberg BDIB 保留期限，无法回补。</div>
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


def _coverage_bg(pct: Optional[float]) -> str:
    """覆盖率数值 → 单元格背景色（渐变）。"""
    if pct is None:
        return "#1a2332"
    if pct >= 99.0:
        return "#1b3a2f"
    if pct >= 90.0:
        return "#2c3a1c"
    if pct >= 50.0:
        return "#3a3418"
    return "#3a1f1f"


def _coverage_text(pct: Optional[float], sla_pct: Optional[float]) -> str:
    """覆盖率文本：双口径一致时只显示一个值，避免列宽膨胀。"""
    if pct is None:
        return "-" if sla_pct is None else f"{sla_pct:.1f}"
    if sla_pct is None or abs(sla_pct - pct) < 0.05:
        return f"{pct:.1f}"
    return f"{pct:.1f} / {sla_pct:.1f}"


def _coverage_cell(
    pct: Optional[float],
    sla_pct: Optional[float] = None,
    reason: Optional[str] = None,
    expected_null: bool = False,
) -> str:
    """覆盖率单元格：「原始 / SLA」双口径 + NULL 原因 tooltip。

    expected_null（结构性必然 NULL，如纯竞价路由的 continuous 指标）以灰底
    虚线边框区分，避免被误判为数据缺陷。
    """
    if pct is None and sla_pct is None:
        return '<td style="color:#5f7186">-</td>'
    # 底色由 SLA 口径决定：SLA 无值（SLA 分母为 0）时回退原始口径，避免整格失色
    bg_pct = sla_pct if sla_pct is not None else pct
    style = f"background:{_coverage_bg(bg_pct)}"
    if expected_null:
        style += ";border:1px dashed #5f7186"
    title = f' title="NULL 原因：{_esc(reason)}"' if reason else ""
    return f'<td style="{style}"{title}>{_esc(_coverage_text(pct, sla_pct))}</td>'


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


def _fmt_hit(hit: dict[str, Any]) -> str:
    """命中规则展示：标签 + 超限具体数值（含单位）。"""
    value = hit.get("value")
    unit = hit.get("unit")
    suffix = " bps" if unit == "bps" else "%"
    val = _fmt_num(value, 1) if value is not None else "-"
    return f"{hit.get('label', '')} {val}{suffix}"


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


def _fmt_money(value: Optional[float], currency: Optional[str]) -> str:
    """成交金额格式化（带币种前缀）；None → '-'。"""
    if value is None:
        return "-"
    ccy = (currency or "").upper()
    prefix = f"{ccy} " if ccy else ""
    return f"{prefix}{_fmt_big(value)}"


def _fx_coverage_sub(kpi: dict[str, Any]) -> str:
    """总成交金额卡片的副标题：USD 换算成功率与被排除金额。

    三态明确区分：无 fx_rate 列 / 无数据 / 覆盖率（含本币被排除金额）。
    """
    coverage = kpi.get("fx_coverage")
    excluded = kpi.get("notional_usd_excluded")
    if coverage is None:
        return "USD 换算 · 无 fx_rate 列"
    pct = coverage * 100.0
    text = "USD 换算 · 全覆盖" if pct >= 99.0 else f"USD 换算 · 覆盖率 {pct:.0f}%"
    if excluded:
        text += f"（本币排除 {_fmt_big(excluded)}）"
    return text


def _fmt_risk(stddev: Optional[float], cvar: Optional[float]) -> str:
    """风险卡片：stddev / CVaR 合并展示。"""
    if stddev is None and cvar is None:
        return "-"
    s = "-" if stddev is None else f"{stddev:.2f}"
    c = "-" if cvar is None else f"{cvar:.2f}"
    return f"{s} / {c}"


def _fmt_order_par_rate(value: Optional[float], flagged: bool = False) -> str:
    """订单参与率展示：同一订单（同交易日同交易所）各路由 par_rate 之和。

    可能 > 100%（语义上即「订单参与率超过市场成交量」的数据异常信号），
    故不封顶；命中 order_par_gt100 规则时追加标记。
    """
    if value is None:
        return "-"
    text = f"{value * 100.0:.2f}%"
    if not flagged:
        return text
    return f'{text} <span class="tag tag-overfill">&gt;100%</span>'


def _fmt_int(value: Optional[float]) -> str:
    """整数（如填充笔数）格式化，None → '-'；带千分位。"""
    if value is None:
        return "-"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _fmt_pct(value: Optional[float]) -> str:
    """百分比展示（0-1 小数 → %，None → '-'）。

    不做封顶：完成率 > 100%（fill > RouteShares）属数据矛盾，应显式暴露而非
    被展示层掩盖（由 overfill_pct 规则与 overfill 标记承接）。
    """
    if value is None:
        return "-"
    return f"{value * 100.0:.2f}%"


def _fmt_pct_raw(value: Optional[float]) -> str:
    """已是百分数（0-100）的值展示，None → '-'。"""
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _fmt_overfill_cell(value: Optional[float], flagged: bool) -> str:
    """完成率单元格：命中 overfill（成交超过委托）时追加警告标记。"""
    text = _fmt_pct(value)
    if not flagged:
        return text
    return f'{text} <span class="tag tag-overfill">超成交</span>'


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


def _esc(text: Any) -> str:
    """HTML 转义。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
