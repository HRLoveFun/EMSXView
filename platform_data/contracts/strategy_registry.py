"""算法策略参数注册表与外部白名单契约（057 DL-16）。

两部分：
1. 策略注册表：策略清单/参数 Schema/默认值/适用市场集中管理——提交前校验、
   存量回填、审计版本的单一真相源（族字段复用 DL-04 algo_taxonomy）；
2. 外部算法白名单接入预留（用户 2026-10-23 追加）：(broker, algo) 合规准入
   名单——样板格式为 `Algo Checklist - YYYY-MM-DD.xlsx`（Broker Code 列 +
   横向策略列表），文件在仓库外由业务维护，系统只读；v0 提供检查能力，
   提交链路阻断由 DL-17 硬约束引擎经特性开关启用（G2）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 注册表版本：结构/种子变更时升版（提交审计记录所用版本）
REGISTRY_VERSION = "strategy-registry-v1"

# 外部白名单路径环境变量（仓库外配置；合规数据不落库、不进 git）
WHITELIST_PATH_ENV = "EMSXVIEW_ALGO_WHITELIST"


@dataclass(frozen=True)
class StrategySpec:
    """策略注册表条目（核心策略；broker 专有高级算法仅族级归类，不入 spec）。

    param_schema：通用参数 schema 摘要——{参数名: {type, required, default,
    description}}；broker 动态字段（strategyParams.fields）透传不在此约束。
    markets：适用市场族（DL-03 market_code_for 折叠码；空=全部）。
    """

    strategy_type: str
    display_name: str
    family: str
    param_schema: dict = field(default_factory=dict)
    markets: tuple[str, ...] = ()
    sort_order: int = 100


# ── 注册表种子（核心策略；param_schema 摘要对齐 route_plans 既有默认值载体） ──

_COMMON_PARTICIPATION = {
    "type": "float",
    "required": False,
    "default": None,
    "description": "目标参与率上限（小数，如 0.18）",
}
_COMMON_WINDOW = {
    "type": "str",
    "required": False,
    "default": None,
    "description": "执行窗口（HH:MM-HH:MM，交易所本地时间）",
}

STRATEGY_REGISTRY: dict[str, StrategySpec] = {
    "VWAP": StrategySpec(
        strategy_type="VWAP",
        display_name="VWAP",
        family="vwap",
        param_schema={
            "participation_rate": _COMMON_PARTICIPATION,
            "window": _COMMON_WINDOW,
        },
        sort_order=10,
    ),
    "TWAP": StrategySpec(
        strategy_type="TWAP",
        display_name="TWAP",
        family="twap",
        param_schema={
            "participation_rate": _COMMON_PARTICIPATION,
            "window": _COMMON_WINDOW,
        },
        sort_order=20,
    ),
    "POV": StrategySpec(
        strategy_type="POV",
        display_name="POV",
        family="pov",
        param_schema={
            "participation_rate": {
                "type": "float",
                "required": True,
                "default": None,
                "description": "目标参与率（小数，POV 必填）",
            },
        },
        sort_order=30,
    ),
    "CLOSE": StrategySpec(
        strategy_type="CLOSE",
        display_name="Close（收盘竞价）",
        family="auction_close",
        param_schema={
            "window": _COMMON_WINDOW,
        },
        sort_order=40,
    ),
    "IS": StrategySpec(
        strategy_type="IS",
        display_name="Implementation Shortfall",
        family="is",
        param_schema={
            "participation_rate": _COMMON_PARTICIPATION,
            "urgency": {
                "type": "str",
                "required": False,
                "default": "MEDIUM",
                "description": "紧急度（LOW/MEDIUM/HIGH）",
            },
        },
        sort_order=50,
    ),
    "DMA": StrategySpec(
        strategy_type="DMA",
        display_name="Direct Market Access",
        family="dma",
        param_schema={},
        sort_order=60,
    ),
}


# ── 策略名归一化与族归类（白名单 110 名核心归类 + DL-04 规则兜底） ─────────────

def normalize_algo_name(name: str | None) -> str:
    """策略名归一化：upper + strip + 去尾点（与 DL-04 同口径）。"""
    text = (name or "").strip().upper()
    return text.rstrip(".") if text.endswith(".") else text


# 白名单样板 110 个 distinct 策略名中，核心命名变体 → 细分族
# （与 DL-04 STRATEGY_TYPE_MAP 的 broker×strategy 精确表互补——此处按名归类）
_ALGO_NAME_FAMILY: dict[str, str] = {
    # vwap 族
    "VWAP": "vwap", "VWAP-EU": "vwap", "VWAP_ADP": "vwap", "VWAP AI": "vwap",
    # twap 族
    "TWAP": "twap", "TWAP-EU": "twap", "TWAP_ADP": "twap",
    "TIMESLICE": "twap", "TIMESTRKE": "twap",
    # pov 族（参与率类，跨 broker 命名高度不一致）
    "POV": "pov", "PART": "pov", "PARTCIPTE": "pov", "PRTICP": "pov",
    "PRTICPATE": "pov", "WITH-VOL": "pov", "V-INLINE": "pov", "VOLINLINE": "pov",
    "INLINE": "pov", "INLN_ADP": "pov", "PXINLINE": "pov", "DYNAMPOV": "pov",
    "DYNAPART": "pov", "STEPPART": "pov", "STEP PART": "pov", "TARGETPOV": "pov",
    # auction_close 族（收盘类）
    "CLOSE": "auction_close", "CLOSE(AP)": "auction_close", "AUCTION": "auction_close",
    "AUCTIONEU": "auction_close", "MOC": "auction_close", "QMOC": "auction_close",
    "QMOC_APEU": "auction_close", "AT CLOSE": "auction_close", "INTOCLOSE": "auction_close",
    "ONCLOSE": "auction_close", "HSBCCLOSE": "auction_close", "SMARTMOC": "auction_close",
    "TCLOSE": "auction_close", "TCLOSE-EU": "auction_close", "TARGETCL": "auction_close",
    "TARGETCLO": "auction_close", "TARGETCLS": "auction_close", "CLOSETGT": "auction_close",
    "CLOSER": "auction_close", "CLOSEPLUS": "auction_close", "MOCDIRECT": "auction_close",
    "MOC_ADP": "auction_close", "TGTCLOSE": "auction_close",
    # auction_open 族（开盘类）
    "ONOPEN": "auction_open", "OPEN": "auction_open", "OPENPLUS": "auction_open",
    "MOO_ADP": "auction_open", "OPP_ADP": "auction_open",
    # is 族
    "IS": "is", "IS_ADP": "is", "ARRIVAL": "is",
    # dma 族
    "DMA": "dma", "SMART DMA": "dma", "SMARTDMA": "dma", "SORDMA": "dma",
    "SORT DMA": "dma",
    # close 族（自定义；管道归 close，语义非明确竞价——DL-04 既有决策）
    "CUSTOM": "close", "CUSTOM1": "close", "CUSTOM2": "close",
}


def resolve_family(strategy_type: str | None) -> str:
    """归一化策略名 → DL-04 细分族；未归类 → unmapped（显式，不静默归 other）。"""
    from platform_data.contracts.algo_taxonomy import STRATEGY_TYPE_RULES

    name = normalize_algo_name(strategy_type)
    family = _ALGO_NAME_FAMILY.get(name)
    if family is not None:
        return family
    for keyword, rule_family in STRATEGY_TYPE_RULES:
        if keyword in name:
            return rule_family
    return "unmapped"


def validate_strategy_params(strategy_type: str | None, params: dict | None) -> list[str]:
    """参数校验（纯函数）：未知策略 / 必填缺失 / 类型不符。空列表 = 通过。"""
    errors: list[str] = []
    name = normalize_algo_name(strategy_type)
    spec = STRATEGY_REGISTRY.get(name)
    if spec is None:
        # 未入注册表 ≠ 阻断：可能是 broker 专有高级算法（族级归类即可）
        return []
    values = params or {}
    for param, rule in spec.param_schema.items():
        if param not in values or values[param] in (None, ""):
            if rule.get("required"):
                errors.append(f"{name}: 必填参数 {param} 缺失")
            continue
        expected = rule.get("type")
        if expected == "float" and not isinstance(values[param], (int, float)):
            errors.append(f"{name}: 参数 {param} 应为数值")
        if expected == "str" and not isinstance(values[param], str):
            errors.append(f"{name}: 参数 {param} 应为字符串")
    return errors


def default_params(strategy_type: str | None) -> dict:
    """注册表默认值（存量回填用；仅返回 schema 中 default 非空的参数）。"""
    name = normalize_algo_name(strategy_type)
    spec = STRATEGY_REGISTRY.get(name)
    if spec is None:
        return {}
    return {
        param: rule["default"]
        for param, rule in spec.param_schema.items()
        if rule.get("default") not in (None, "")
    }


# ── 外部算法白名单（用户 2026-10-23 追加；样板 Algo Checklist xlsx） ──────────

@dataclass(frozen=True)
class AlgoWhitelist:
    """(broker → 归一化策略名集合) 合规准入名单。

    source_path/loaded_at/row_count 供审计（提交记录附 whitelist_version）。
    """

    brokers: dict[str, frozenset[str]]
    source_path: str
    loaded_at: str
    row_count: int


@dataclass(frozen=True)
class ComplianceResult:
    """白名单合规检查结果（v0 检查能力；阻断由 DL-17 经开关启用）。"""

    allowed: bool
    reason: str


def load_algo_whitelist(path: str | None = None) -> Optional[AlgoWhitelist]:
    """加载白名单（xlsx 样板格式；缺失/未配置返回 None=未知，不阻断）。

    样板格式（Sheet1）：第 3 行表头（Broker Code | Algo in Strategy Menu of EMS），
    第 4 行起每行 broker + 横向策略列表；`NONE` 单元格忽略。
    """
    import os
    from datetime import datetime, timezone

    target = path or os.getenv(WHITELIST_PATH_ENV, "")
    if not target:
        return None
    if not os.path.exists(target):
        return None

    try:
        import openpyxl
    except ImportError:  # 部署环境缺依赖 → 白名单「未知」而非崩溃（不阻断语义）
        import logging

        logging.getLogger(__name__).warning("openpyxl 未安装，算法白名单按未知处理")
        return None

    workbook = openpyxl.load_workbook(target, data_only=True, read_only=True)
    sheet = workbook.worksheets[0]
    brokers: dict[str, frozenset[str]] = {}
    for row in sheet.iter_rows(values_only=True):
        broker = row[0] if row else None
        if not broker or not str(broker).strip():
            continue
        broker_code = str(broker).strip().upper()
        if broker_code in {"BROKER CODE", "ALGO CHECKLIST"}:
            continue  # 表头/标题行
        algos = {
            normalize_algo_name(cell)
            for cell in row[1:]
            if cell and str(cell).strip() and str(cell).strip().upper() != "NONE"
        }
        brokers[broker_code] = frozenset(algos)
    workbook.close()
    if not brokers:
        return None
    return AlgoWhitelist(
        brokers=brokers,
        source_path=target,
        loaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        row_count=len(brokers),
    )


def is_algo_whitelisted(
    whitelist: AlgoWhitelist | None,
    broker: str,
    strategy: str,
) -> bool | None:
    """三态判定：None=白名单未知（放行但记录）；True=在名单；False=不在。"""
    if whitelist is None:
        return None
    algos = whitelist.brokers.get((broker or "").strip().upper())
    if algos is None:
        return False  # broker 不在名单 = 该 broker 无准入算法
    return normalize_algo_name(strategy) in algos


def compliance_check(
    whitelist: AlgoWhitelist | None,
    broker: str,
    strategy: str,
) -> ComplianceResult:
    """合规检查（v0）：白名单未知 → allowed=True（不阻断）；不在名单 → False。"""
    verdict = is_algo_whitelisted(whitelist, broker, strategy)
    if verdict is None:
        return ComplianceResult(allowed=True, reason="whitelist unavailable (not configured)")
    if verdict:
        return ComplianceResult(allowed=True, reason="in algo whitelist")
    return ComplianceResult(
        allowed=False,
        reason=f"not in algo whitelist: broker={broker}, algo={strategy}",
    )
