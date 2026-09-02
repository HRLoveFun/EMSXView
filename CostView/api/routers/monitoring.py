"""CostView 监控 router — /api/tca/monitoring/* 端点。

提供：
  GET /api/tca/monitoring/bdib-health      — BDIB 数据健康（双源扫描 + 四级分级）
  GET /api/tca/monitoring/metric-coverage  — 38 项计算指标覆盖率（日期 × 指标）
  GET /api/tca/monitoring/report-summary   — TCA 可视化报告聚合数据
  GET /api/tca/monitoring/export-html      — 一键导出自包含 HTML 报告（附件下载）

时间范围二选一互斥：start_date/end_date 显式区间 或 last 预设
（day/week/month/quarter/year，默认 day）。冲突输入返回 422。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from CostView.src.monitoring import (
    LAST_PRESETS,
    BdibHealthService,
    MetricCoverageService,
    TcaReportAggregator,
    ThresholdRules,
    TimeRange,
    ANOMALY_RULE_META,
    fetch_latest_tca_date,
    get_default_thresholds,
    get_health_safe,
    render_report_html,
    resolve_time_range,
)
from CostView.src.tca_cache import TcaCacheManager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CostView Monitoring"])

_cache = TcaCacheManager()

_DATE_PATTERN = r"^\d{8}$"


class MonitoringResponse(BaseModel):
    """统一监控响应包装。"""

    success: bool
    data: Optional[dict] = None
    message: str = ""


# ── 公共参数解析 ──────────────────────────────────────────────────────────


def _resolve_range(
    start_date: Optional[str],
    end_date: Optional[str],
    last: Optional[str],
) -> TimeRange:
    """解析互斥时间范围；last=day 时注入最近数据日期。非法输入 → 422。"""
    try:
        latest = fetch_latest_tca_date() if _needs_latest(start_date, end_date, last) else None
        return resolve_time_range(start_date, end_date, last, latest_data_date=latest)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _needs_latest(
    start_date: Optional[str], end_date: Optional[str], last: Optional[str],
) -> bool:
    """是否需要查询最近数据日期（仅 last=day 或全默认时）。"""
    if start_date or end_date:
        return False
    return last in (None, "", "day")


def _parse_metrics(metrics: Optional[str]) -> Optional[list[str]]:
    """逗号分隔的 metrics 查询参数 → 列表。"""
    if not metrics:
        return None
    return [m.strip() for m in metrics.split(",") if m.strip()]


# ── 端点 ──────────────────────────────────────────────────────────────────


@router.get("/api/tca/monitoring/bdib-health", response_model=MonitoringResponse)
async def get_bdib_health(
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    last: Optional[str] = Query(None, description=f"预设: {', '.join(LAST_PRESETS)}"),
):
    """BDIB 健康扫描：按交易日输出覆盖率与 ok/partial/missing/unrecoverable 分级。"""
    tr = _resolve_range(start_date, end_date, last)
    params = {"start": tr.start_date, "end": tr.end_date}
    cache_key = TcaCacheManager.make_key("monitoring:bdib-health", params)

    cached = await _cache.get(cache_key)
    if cached is not None:
        return MonitoringResponse(success=True, data=cached, message="BDIB 健康（缓存）")

    try:
        data = get_health_safe(tr.start_date, tr.end_date, health_service=BdibHealthService)
    except Exception as exc:
        logger.error("BDIB 健康扫描失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"BDIB 健康扫描错误: {exc}")
    if data is None:
        raise HTTPException(
            status_code=503, detail="BDIB 健康扫描超时，请稍后重试或缩小时间范围",
        )

    await _cache.set(cache_key, data)
    summary = data["summary"]
    return MonitoringResponse(
        success=True,
        data=data,
        message=(
            f"{summary['total_dates']} 个交易日，缺口 {summary['partial_dates'] + summary['missing_dates'] + summary['unrecoverable_dates']} 天"
        ),
    )


@router.get("/api/tca/monitoring/metric-coverage", response_model=MonitoringResponse)
async def get_metric_coverage(
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    last: Optional[str] = Query(None, description=f"预设: {', '.join(LAST_PRESETS)}"),
    metrics: Optional[str] = Query(None, description="逗号分隔指标子集，默认全部 38 个"),
    group_by_exchange: bool = Query(False, description="按 Exchange 分层"),
):
    """指标覆盖率：按日期（可选 ×Exchange）统计各指标非 NULL 率。"""
    tr = _resolve_range(start_date, end_date, last)
    selected = _parse_metrics(metrics)
    params = {
        "start": tr.start_date, "end": tr.end_date,
        "metrics": selected, "gbe": group_by_exchange,
    }
    cache_key = TcaCacheManager.make_key("monitoring:metric-coverage", params)

    cached = await _cache.get(cache_key)
    if cached is not None:
        return MonitoringResponse(success=True, data=cached, message="指标覆盖率（缓存）")

    try:
        data = MetricCoverageService().get_coverage(
            tr.start_date, tr.end_date, selected, group_by_exchange,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("指标覆盖率统计失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"指标覆盖率统计错误: {exc}")

    await _cache.set(cache_key, data)
    return MonitoringResponse(
        success=True, data=data,
        message=f"{len(data['rows'])} 个分组 × {len(data['metrics'])} 个指标",
    )


@router.get("/api/tca/monitoring/report-summary", response_model=MonitoringResponse)
async def get_report_summary(
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    last: Optional[str] = Query(None, description=f"预设: {', '.join(LAST_PRESETS)}"),
    broker: Optional[str] = Query(None, max_length=100),
    algo: Optional[str] = Query(None, max_length=50),
    symbol: Optional[str] = Query(None, max_length=100),
    exchange: Optional[str] = Query(None, max_length=20),
    metrics: Optional[str] = Query(None, description="逗号分隔指标子集，默认全部 38 个"),
    thresholds: Optional[str] = Query(None, description="JSON 阈值规则覆盖（异常路由明细判定，与 export-html 同契约）"),
    min_fill_count: int = Query(10, ge=0, description="异常路由填充笔数下限（仅对 algo<>close 生效）"),
    min_notional_usd: float = Query(10000.0, ge=0, description="异常路由成交金额(USD)下限（对全部路由生效）"),
):
    """TCA 报告聚合：KPI、分布直方图、按日走势、broker/algo 排行、PWP 曲线。"""
    tr = _resolve_range(start_date, end_date, last)
    selected = _parse_metrics(metrics)

    # 008: 阈值规则随查询解析（None/空 → 默认阈值），页面异常明细与用户配置对齐
    try:
        rules = ThresholdRules.from_payload(_parse_thresholds(thresholds))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"thresholds 非法: {exc}")

    params = {
        "start": tr.start_date, "end": tr.end_date, "broker": broker,
        "algo": algo, "symbol": symbol, "exchange": exchange, "metrics": selected,
        # 缓存 key 纳入解析后的阈值（sort_keys 归一化；默认阈值与未传等价同 key）
        "thresholds": rules.rules,
        "min_fill_count": min_fill_count, "min_notional_usd": min_notional_usd,
    }
    cache_key = TcaCacheManager.make_key("monitoring:report-summary", params)

    cached = await _cache.get(cache_key)
    if cached is not None:
        return MonitoringResponse(success=True, data=cached, message="报告聚合（缓存）")

    try:
        data = TcaReportAggregator().build_report(
            tr.start_date, tr.end_date,
            broker=broker, algo=algo, symbol=symbol, exchange=exchange,
            metrics=selected, thresholds=rules.rules,
            min_fill_count=min_fill_count, min_notional_usd=min_notional_usd,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("报告聚合失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"报告聚合错误: {exc}")

    await _cache.set(cache_key, data)
    kpi = data.get("kpi") or {}
    return MonitoringResponse(
        success=True, data=data,
        message=f"报告聚合完成：{kpi.get('route_count', 0)} 条路由",
    )


@router.get("/api/tca/monitoring/anomaly-thresholds", response_model=MonitoringResponse)
async def get_anomaly_thresholds():
    """异常路由判定阈值与规则元数据（后端为唯一真相源）。

    前端 Configure / 首装 seed 从此拉取默认阈值与规则标签、指标字段、缩放系数，
    避免前后端双份维护漂移。返回结构：
      data.rules      — 默认阈值（mode/warning/critical/enabled）
      data.rule_meta  — 规则键 → 中文标签 / 指标字段 / 缩放系数
    """
    return MonitoringResponse(
        success=True,
        data={
            "rules": get_default_thresholds(),
            "rule_meta": ANOMALY_RULE_META,
        },
        message="异常路由判定默认阈值",
    )


@router.get("/api/tca/monitoring/export-html")
async def export_tca_html(
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    last: Optional[str] = Query(None, description=f"预设: {', '.join(LAST_PRESETS)}"),
    broker: Optional[str] = Query(None, max_length=100),
    algo: Optional[str] = Query(None, max_length=50),
    symbol: Optional[str] = Query(None, max_length=100),
    exchange: Optional[str] = Query(None, max_length=20),
    metrics: Optional[str] = Query(None, description="逗号分隔指标子集，默认全部 38 个"),
    thresholds: Optional[str] = Query(None, description="JSON 阈值规则覆盖（S6 明细判定）"),
    min_fill_count: int = Query(10, ge=0, description="异常路由填充笔数下限（仅对 algo<>close 生效）"),
    min_notional_usd: float = Query(10000.0, ge=0, description="异常路由成交金额(USD)下限（对全部路由生效）"),
):
    """导出自包含 HTML 报告（附件下载，文件名 tca_report_<start>_<end>.html）。

    内容与 CLI ``generate_tca_report.py`` 同源（同一渲染器）：KPI（10 卡）、
    分布/走势/排行/PWP、市场冲击分解、异常路由明细、指标覆盖率、BDIB 缺口附录。
    含口径脚注（价格偏离，不含费用/L2/事前预测）。
    """
    tr = _resolve_range(start_date, end_date, last)
    selected = _parse_metrics(metrics)

    try:
        rules = ThresholdRules.from_payload(_parse_thresholds(thresholds))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"thresholds 非法: {exc}")

    try:
        report = TcaReportAggregator().build_report(
            tr.start_date, tr.end_date,
            broker=broker, algo=algo, symbol=symbol, exchange=exchange,
            metrics=selected, thresholds=rules.rules, min_fill_count=min_fill_count, min_notional_usd=min_notional_usd,
        )
        health = _load_health_appendix(tr.start_date, tr.end_date)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.error("HTML 报告生成失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"HTML 报告错误: {exc}")

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html = render_report_html(report, health, generated_at)
    filename = f"tca_report_{tr.start_date}_{tr.end_date}.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


def _parse_thresholds(raw: Optional[str]) -> Optional[dict]:
    """解析 thresholds JSON 查询参数；None/空 → None（默认阈值）。"""
    if not raw:
        return None
    import json
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析失败: {exc}")
    if not isinstance(parsed, dict):
        raise ValueError("thresholds 必须是 JSON 对象")
    return parsed


def _load_health_appendix(start_date: str, end_date: str) -> Optional[dict]:
    """加载 BDIB 健康数据作附录；带超时护栏（导出态超时较短，避免拖垮报告），
    超时/失败降级为 None 不阻断报告。"""
    return get_health_safe(start_date, end_date, timeout=12.0, health_service=BdibHealthService)
