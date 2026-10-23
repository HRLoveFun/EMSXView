"""算法参数合规契约（057 DL-17c/073）——纯数据 + 纯函数，无 IO。

四项合规（交易员意见 2026-10-23 第 11–14 项）：
1. 券商算法白名单「未命中或未知均不放行、转人工」（语义修订在服务层，见
   backend/api/services/strategy_registry.py）；
2. 每路由必带 volume cap（券商命名映射，复用既有每券商 JSON 记录模式）；
3. volume cap 分配：**同日同名且同方向**按数量比例、精度 0.1、加总 ≤18.0
   （非 EUR）/ ≤9.0（EUR）、新单与轧差后重算；
4. 收盘拍卖订单必带 release time（避免过早到达暴露方向）。
"""

from __future__ import annotations

import math

# 契约版本：口径变更时升版
ALGO_PARAMS_VERSION = "algo-params-v1"

# volume cap 总额度上限（交易员意见：非 EUR 18.0 / EUR 9.0）
MAX_VOLUME_CAP_NON_EUR = 18.0
MAX_VOLUME_CAP_EUR = 9.0

# 分配精度（交易员意见：精确到小数点后 1 位）
VOLUME_CAP_PRECISION = 0.1

# 券商参数的缺省命名（映射未命中时使用，且检查结果标注来源）
DEFAULT_VOLUME_CAP_PARAM = "PctVol"

# release time 参数名（EMSX 惯例；交易员意见未要求按券商映射）
RELEASE_TIME_PARAM = "release_time"

# 收盘拍卖市场：DL-03 注册表 closing_auction 存在即需 release time。
# 迁移集合（EARLY_CLOSE_AUCTION_EXCHANGES）为「竞价提前开始」的市场，同样覆盖。
_EUR_MARKET_ALIASES = {"EU", "EUR"}


def max_cap_for(currency: str | None = None, market_code: str | None = None) -> float:
    """总额度上限：EUR（货币或折叠市场码）→ 9.0，其余 → 18.0。"""
    if (currency or "").strip().upper() == "EUR":
        return MAX_VOLUME_CAP_EUR
    if (market_code or "").strip().upper() in _EUR_MARKET_ALIASES:
        return MAX_VOLUME_CAP_EUR
    return MAX_VOLUME_CAP_NON_EUR


def param_name_for(broker: str, mapping: dict[str, str] | None = None) -> tuple[str, str]:
    """券商 volume cap 参数名 → (name, source)。

    source：'record'（既有每券商 JSON 记录命中）/ 'default'（缺省 PctVol，
    可观测不静默）。映射沿用 broker_hand_instruction.json 的「每券商 → 单值」
    记录模式（用户 2026-10-23：每券商具体命名使用已有记录）。
    """
    key = (broker or "").strip()
    if mapping and key in mapping:
        return mapping[key], "record"
    return DEFAULT_VOLUME_CAP_PARAM, "default"


def allocate_volume_caps(
    legs: list[tuple[str, float]],
    max_cap: float,
    *,
    precision: float = VOLUME_CAP_PRECISION,
) -> dict[str, float]:
    """同日同名**且同方向**订单组的 volume cap 比例分配。

    legs：[(order_id, qty)]（同 ticker 同 side；不同方向先经 072 轧差，不会
    进入本函数）。按数量比例分配，**向下取整到 precision** 保证
    sum ≤ max_cap；取整损失的额度追加给数量最大的一单（仍 ≤ max_cap）。

    边界：空组 / 全零数量 → 返回空 dict（调用方转人工，不猜）。
    """
    valid = [(oid, float(qty)) for oid, qty in legs if qty and float(qty) > 0]
    if not valid or max_cap <= 0 or precision <= 0:
        return {}
    total = sum(qty for _, qty in valid)
    if total <= 0:
        return {}

    steps = int(math.floor(max_cap / precision))
    allocation: dict[str, float] = {}
    assigned_steps = 0
    for order_id, qty in valid:
        share_steps = int(math.floor(qty / total * max_cap / precision))
        share_steps = min(share_steps, max(0, steps - assigned_steps))
        if share_steps > 0:
            allocation[order_id] = round(share_steps * precision, 10)
            assigned_steps += share_steps

    # 取整余量给数量最大的一单（保证不超 max_cap、不浪费额度）
    remaining_steps = steps - assigned_steps
    if remaining_steps > 0 and allocation:
        biggest = max(valid, key=lambda item: item[1])[0]
        allocation[biggest] = round(allocation.get(biggest, 0.0) + remaining_steps * precision, 10)
    return allocation


def release_time_required(market_code: str) -> bool:
    """收盘拍卖市场 → 订单必须携带 release time。"""
    from platform_data.contracts import SESSION_REGISTRY

    market = (market_code or "").strip().upper()
    session = SESSION_REGISTRY.get(market)
    return session is not None and bool(session.closing_auction)


def check_volume_cap_present(
    params: dict | None,
    broker: str,
    *,
    mapping: dict[str, str] | None = None,
) -> list[str]:
    """每路由必带 volume cap：按券商命名查找，缺失/空值返回错误（空列表=通过）。"""
    name, source = param_name_for(broker, mapping)
    value = (params or {}).get(name)
    if value is None or value == "":
        return [
            f"volume cap parameter {name!r} missing for broker {broker!r} "
            f"(name_source={source})"
        ]
    return []


def check_release_time_present(params: dict | None, market_code: str) -> list[str]:
    """收盘拍卖市场订单必带 release time；非收盘拍卖市场不要求。"""
    if not release_time_required(market_code):
        return []
    value = (params or {}).get(RELEASE_TIME_PARAM)
    if value is None or value == "":
        return [
            f"closing-auction order in {market_code!r} requires {RELEASE_TIME_PARAM!r} "
            f"(avoid early exposure to broker)"
        ]
    return []
