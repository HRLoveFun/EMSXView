"""执行简报 router — ``GET /api/tca/brief``（230）。

期间可选：``last=day|week|month|quarter|year`` 或显式 ``start_date/end_date``
（YYYYMMDD，二选一）。维度筛选与交易员复盘台同语义（逗号分隔多值，任一路由命中）。

只读端点；合并模式（core :3000）与独立模式（CostView :8002）共用同一路由。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from CostView.api.concurrency import QueryTimeoutError, run_bounded
from CostView.src import execution_brief
from CostView.src.execution_brief import DataNotReadyError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CostView Brief"])

_DATE_PATTERN = r"^\d{8}$"


class BriefResponse(BaseModel):
    """统一执行简报响应包装（与 costview / trader 端点同信封）。"""

    success: bool
    data: Optional[dict] = None
    message: str = ""


@router.get("/api/tca/brief", response_model=BriefResponse)
async def get_execution_brief(
    last: Optional[str] = Query(
        None, pattern="^(day|week|month|quarter|year)$",
        description="期间预设：day/week/month/quarter/year（与 start/end 二选一）",
    ),
    start_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    end_date: Optional[str] = Query(None, pattern=_DATE_PATTERN),
    trader: Optional[str] = Query(None, max_length=200, description="TraderName，逗号分隔"),
    ticker: Optional[str] = Query(None, max_length=200, description="equ_ticker，逗号分隔"),
    exchange: Optional[str] = Query(None, max_length=200, description="市场，逗号分隔"),
    side: Optional[str] = Query(None, max_length=20, description="BUY/SELL，逗号分隔"),
    strategy_type: Optional[str] = Query(None, max_length=200, description="StrategyType，逗号分隔"),
    algo: Optional[str] = Query(None, max_length=200, description="algo，逗号分隔"),
    broker: Optional[str] = Query(None, max_length=200, description="Broker，逗号分隔"),
    top_n: int = Query(10, ge=1, le=50, description="Top 订单条数"),
):
    """执行简报：订单级概览 / 买卖拆分 / 完成分桶 / 成本桥 / 异常 / 数据缺口。"""
    try:
        # 大区间（季度/年度）订单级聚合为同步重查询：卸载到线程池并受并发/超时护栏，
        # 避免阻塞事件循环（与 analyze / 交易员导出同一约定）。
        data = await run_bounded(
            execution_brief.build_brief,
            start_date=start_date, end_date=end_date, last=last,
            trader=trader, ticker=ticker, exchange=exchange, side=side,
            strategy_type=strategy_type, algo=algo, broker=broker,
            top_n=top_n,
        )
    except QueryTimeoutError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "query_timeout", "message": str(exc)},
        )
    except DataNotReadyError as exc:
        raise HTTPException(
            status_code=503, detail={"code": "data_not_ready", "message": str(exc)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "data_source_unavailable",
                "message": f"CostView database not found: {exc}",
            },
        )
    except Exception as exc:  # noqa: BLE001 - 路由层统一转 500
        logger.error("执行简报查询失败: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"执行简报查询错误: {exc}")

    return BriefResponse(
        success=True, data=data,
        message=f"执行简报 {data['period']['start_date']}~{data['period']['end_date']}",
    )
