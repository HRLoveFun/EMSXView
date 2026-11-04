"""CostView 交易员复盘台 router — /api/tca/trader/* 端点（PR-1）。

提供：
  GET /api/tca/trader/orders          — 订单列表（服务端分页/排序 + KPI + 质量探针）
  GET /api/tca/trader/filter-options  — 筛选下拉（traders/strategy_types + 复用维度表）

全部端点返回 `{ success, data, message }` 信封；GET 查询，桥接模式只要求有效
token（backend 侧 _bridge_guard 统一施加）。只读：不写任何数据库。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from CostView.api.concurrency import QueryTimeoutError, run_bounded
from CostView.src import trader_service
from CostView.src.trader_service import DataNotReadyError, OrderNotFound

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CostView Trader"])

_DATE_PATTERN = r"^\d{8}$"


class TraderResponse(BaseModel):
    """统一交易员视图响应包装。"""

    success: bool
    data: Optional[dict] = None
    message: str = ""


@router.get("/api/tca/trader/orders", response_model=TraderResponse)
async def list_trader_orders(
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    trader: Optional[str] = Query(None, max_length=200, description="TraderName，逗号分隔多值"),
    ticker: Optional[str] = Query(None, max_length=200, description="equ_ticker 精确匹配，逗号分隔"),
    side: Optional[str] = Query(None, max_length=20, description="BUY/SELL，逗号分隔"),
    strategy_type: Optional[str] = Query(None, max_length=200),
    algo: Optional[str] = Query(None, max_length=200),
    broker: Optional[str] = Query(None, max_length=200),
    completion_bucket: Optional[str] = Query(
        None, description="lt50/50to80/80to100/eq100/gt100",
    ),
    quality: Optional[str] = Query(
        None, description="all/clean/overfill/cost_missing/par_suspect/single_fill",
    ),
    sort: str = Query("date", description="date/completion/arrival_bps/opp_cost/notional/route_count"),
    sort_dir: str = Query("desc", description="asc/desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """订单复盘列表：订单级聚合在 SQL 完成；多路由「任一路由命中」过滤。

    默认日期 = 最近 5 个交易日；空结果返回 200 + total_orders=0；
    默认窗口内无任何 TCA 汇总时返回 503 data_not_ready（沿用既有约定）。
    """
    try:
        data = trader_service.build_order_page_from_query(
            start_date=start_date, end_date=end_date,
            trader=trader, ticker=ticker, side=side,
            strategy_type=strategy_type, algo=algo, broker=broker,
            completion_bucket=completion_bucket, quality=quality,
            sort=sort, sort_dir=sort_dir, limit=limit, offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except DataNotReadyError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "data_not_ready", "message": str(exc)},
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "data_source_unavailable",
                "message": f"CostView database not found: {exc}",
            },
        )
    except Exception as exc:
        logger.error("交易员订单列表失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"交易员订单列表错误: {exc}")

    return TraderResponse(
        success=True,
        data=data,
        message=f"订单 {len(data['orders'])}/{data['total_orders']} 条（offset={data['offset']}）",
    )


@router.get("/api/tca/trader/orders/{order_id}", response_model=TraderResponse)
async def get_trader_order_detail(
    order_id: str,
    order_as_of_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    bucket_min: int = Query(5, description="时间桶宽（分钟）：5 / 15"),
):
    """订单详情（§3.4.2）：routes / fills / 时间线（逐桶参与率）/ 成本分解等。

    不含 peer（避免阻塞）；daily（P2）暂为 null；跨日订单需显式 order_as_of_date。
    """
    try:
        data = trader_service.build_order_detail(
            order_id, order_as_of_date=order_as_of_date, bucket_min=bucket_min,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "data_source_unavailable",
                "message": f"CostView database not found: {exc}",
            },
        )
    except Exception as exc:
        logger.error("订单详情查询失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"订单详情查询错误: {exc}")

    return TraderResponse(success=True, data=data, message=f"订单 {order_id} 详情")


@router.get("/api/tca/trader/orders/{order_id}/peer", response_model=TraderResponse)
async def get_trader_order_peer(
    order_id: str,
    order_as_of_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
):
    """同类 peer 分位（§3.4.3 / §4.7）：8 维指纹 + 两级口径 + 延迟 p90。

    与详情分离（懒加载）：peer 需要 180 天同类样本聚合，不应阻塞详情首屏。
    样本不足时返回 `sample_insufficient=true` 且分位为 null（不返回伪分位）。
    """
    try:
        data = trader_service.build_order_peer(
            order_id, order_as_of_date=order_as_of_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "data_source_unavailable",
                "message": f"CostView database not found: {exc}",
            },
        )
    except Exception as exc:
        logger.error("订单 peer 查询失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"订单 peer 查询错误: {exc}")

    return TraderResponse(success=True, data=data, message=f"订单 {order_id} peer 分位")


@router.get("/api/tca/trader/export")
async def export_trader_csv(
    kind: str = Query(..., pattern="^(orders|fills)$", description="orders / fills"),
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    trader: Optional[str] = Query(None, max_length=200, description="TraderName，逗号分隔多值"),
    ticker: Optional[str] = Query(None, max_length=200, description="equ_ticker，逗号分隔"),
    side: Optional[str] = Query(None, max_length=20, description="BUY/SELL，逗号分隔"),
    strategy_type: Optional[str] = Query(None, max_length=200),
    algo: Optional[str] = Query(None, max_length=200),
    broker: Optional[str] = Query(None, max_length=200),
    completion_bucket: Optional[str] = Query(None, description="lt50/50to80/80to100/eq100/gt100"),
    quality: Optional[str] = Query(
        None, description="all/clean/overfill/cost_missing/par_suspect/single_fill",
    ),
    sort: str = Query("date", description="date/completion/arrival_bps/opp_cost/notional/route_count"),
    sort_dir: str = Query("desc", description="asc/desc"),
    order_id: Optional[str] = Query(None, max_length=100, description="导出单笔订单"),
):
    """CSV 导出（§3.4.4 / §4.14）：与列表同筛选，不含分页。

    UTF-8-SIG + 3 行 ``#`` 注释（spec_version / generated_at / filters）；
    orders 超 50,000 / fills 超 500,000 → 422 要求缩小范围（不静默截断）。
    """
    try:
        # 预检（订单聚合 + fills 行数 COUNT，最坏 500k 行）是同步重查询：
        # 走 run_bounded 卸载到线程池并受并发/超时护栏约束，避免冻结事件循环
        chunks, filename = await run_bounded(
            trader_service.stream_export_csv,
            kind,
            start_date=start_date, end_date=end_date,
            trader=trader, ticker=ticker, side=side,
            strategy_type=strategy_type, algo=algo, broker=broker,
            completion_bucket=completion_bucket, quality=quality,
            sort=sort, sort_dir=sort_dir, order_id=order_id,
        )
    except QueryTimeoutError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "query_timeout", "message": str(exc)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except OrderNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DataNotReadyError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "data_not_ready", "message": str(exc)},
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "data_source_unavailable",
                "message": f"CostView database not found: {exc}",
            },
        )
    except Exception as exc:
        # 合并模式下 5xx 字符串 detail 会被遮蔽为 "Internal server error"
        # （backend/api/errors.py）；结构化 code 白名单放行，但文案不得携带内部异常内容
        logger.error("交易员 CSV 导出失败: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "export_failed",
                "message": "交易员 CSV 导出失败，请缩小范围后重试；持续失败请联系运维",
            },
        )

    return StreamingResponse(
        chunks,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/tca/trader/filter-options", response_model=TraderResponse)
async def list_trader_filter_options(
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    ticker_prefix: Optional[str] = Query(None, max_length=20, description="Ticker 自动补全前缀"),
):
    """筛选下拉：traders/strategy_types 取 tca_route_summary DISTINCT，其余复用维度表。"""
    try:
        data = trader_service.build_filter_options(
            start_date=start_date, end_date=end_date, ticker_prefix=ticker_prefix,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "data_source_unavailable",
                "message": f"CostView database not found: {exc}",
            },
        )
    except Exception as exc:
        logger.error("筛选选项查询失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"筛选选项查询错误: {exc}")

    return TraderResponse(success=True, data=data, message="筛选选项")
