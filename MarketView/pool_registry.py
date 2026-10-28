"""指数池注册表（057 节点一重定义）。

指数成分股由管道侧 ``index_constituent`` 表提供（尚未就绪），因此 v0 只读仓库内
配置 ``MarketView/pools/index_pools.json``：**开发验证用的 ticker 清单**，不是实时
指数成分。接入顺序与判定见 ``specs/057-execution-decision-loop/tasks.md`` DL-31。

本模块只做两件事：读配置、把行情交易所码规范成会话注册表的键（``GY``/``EU`` →
``GR``、``CH`` → ``C1``），不触库、不写盘。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from platform_data.contracts.exchange_session_contracts import SESSION_REGISTRY
from platform_data.contracts.monitor_contracts import MonitorPoolMember

CONFIG_PATH = Path(__file__).resolve().parent / "pools" / "index_pools.json"
DEFAULT_POOL_ID = "dev-validation"

# 行情侧交易所码 → 会话注册表键（与 MarketView/market_clock.py 的别名保持一致）
MARKET_CODE_ALIASES = {"CH": "C1", "EU": "GR", "GY": "GR"}


@dataclass(frozen=True)
class IndexPool:
    pool_id: str
    label: str
    description: str
    source: str
    as_of: str
    members: tuple[MonitorPoolMember, ...]


def market_code_for(exchange: str) -> str:
    """'GY' → 'GR'；未注册的市场原样返回，由调用方标 unknown。"""
    code = (exchange or "").strip().upper()
    code = MARKET_CODE_ALIASES.get(code, code)
    return code if code in SESSION_REGISTRY else (code or "unknown")


@lru_cache(maxsize=1)
def load_pools() -> tuple[IndexPool, ...]:
    """读配置并缓存；文件缺失/损坏时抛错（不静默返回空池）。"""
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    as_of = str(payload.get("updated_at") or "")
    pools: list[IndexPool] = []
    for item in payload.get("pools", []):
        members = tuple(
            MonitorPoolMember(
                equ_ticker=str(member["equ_ticker"]).strip(),
                name=(member.get("name") or None),
                exchange=str(member.get("exchange") or "").strip().upper(),
                market_code=market_code_for(str(member.get("exchange") or "")),
            )
            for member in item.get("members", [])
            if member.get("equ_ticker")
        )
        pools.append(
            IndexPool(
                pool_id=str(item["pool_id"]),
                label=str(item.get("label") or item["pool_id"]),
                description=str(item.get("description") or ""),
                source="config",
                as_of=as_of,
                members=members,
            )
        )
    return tuple(pools)


def list_pools() -> list[IndexPool]:
    return list(load_pools())


def get_pool(pool_id: str | None = None) -> IndexPool:
    """按 pool_id 取池；未指定时用默认验证池，未知池抛 ValueError（路由转 422）。"""
    pools = load_pools()
    target = pool_id or DEFAULT_POOL_ID
    for pool in pools:
        if pool.pool_id == target:
            return pool
    raise ValueError(f"Unknown index pool: {target}")
