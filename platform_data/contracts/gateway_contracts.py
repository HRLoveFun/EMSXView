"""行情/参考数据网关契约（013）——纯数据，无 IO。

Ownership：**EMSXDataPipeline 定义**（网关是提供方）。本文件是 EMSXView 侧的
**镜像**，逐项对齐上游 `tests/contracts/gateway_schema.json` 的
`contractVersion` / `errorCodes` / `limits` / `fieldCatalog`。

修改纪律（重要）：
- 不得为了让客户端"跑通"而改这里的字段名或错误码；契约变更必须回到上游
  改 schema、升 `contractVersion`，再同步本文件与同名 JSON 镜像。
- 本文件与 `gateway_schema.json` 的一致性由
  `backend/api/tests/test_gateway_contract_mirror.py` 守护。

与 `intraday_store_contracts.py` 同属「契约先行」模式：上游冻结、下游镜像、
双侧测试锁定。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

# ── 版本与传输 ────────────────────────────────────────────────────────────────

#: 契约版本。网关 /health 返回同名字段，客户端启动时断言一致。
CONTRACT_VERSION = "gateway-v1"

#: 上游 schema 镜像的文件名（同目录）。缺文件即视为契约未同步。
SCHEMA_MIRROR_FILE = "gateway_schema.json"

HTTP_PREFIX = "/api/gw/v1"
WS_MARKETDATA_PATH = "/ws/gw/v1/marketdata"


# ── 错误码 ────────────────────────────────────────────────────────────────────


class ErrorCode(IntEnum):
    """网关业务错误码（与 schema errorCodes 一一对应）。"""

    OK = 0
    INVALID_ARGUMENT = 1001
    UPSTREAM_UNAVAILABLE = 2001
    SUBSCRIPTION_LIMIT = 2002
    UPSTREAM_TIMEOUT = 2003
    FIELD_UNAVAILABLE = 2004
    INTERNAL_ERROR = 3001


class ClientAction:
    """错误码对应的客户端动作（避免各调用点自行发明降级策略）。"""

    NONE = "none"
    FIX_REQUEST = "fix_request"
    FALLBACK_DIRECT = "fallback_direct"
    SHRINK_UNIVERSE = "shrink_universe"
    USE_STALE = "use_stale"
    MARK_GAP = "mark_gap"


@dataclass(frozen=True)
class ErrorSpec:
    """单个错误码的完整定义。"""

    code: int
    name: str
    http: int
    retryable: bool
    client_action: str


ERROR_SPECS: dict[int, ErrorSpec] = {
    ErrorCode.OK: ErrorSpec(0, "OK", 200, False, ClientAction.NONE),
    ErrorCode.INVALID_ARGUMENT: ErrorSpec(
        1001, "INVALID_ARGUMENT", 400, False, ClientAction.FIX_REQUEST
    ),
    ErrorCode.UPSTREAM_UNAVAILABLE: ErrorSpec(
        2001, "UPSTREAM_UNAVAILABLE", 503, True, ClientAction.FALLBACK_DIRECT
    ),
    ErrorCode.SUBSCRIPTION_LIMIT: ErrorSpec(
        2002, "SUBSCRIPTION_LIMIT", 429, False, ClientAction.SHRINK_UNIVERSE
    ),
    ErrorCode.UPSTREAM_TIMEOUT: ErrorSpec(
        2003, "UPSTREAM_TIMEOUT", 504, True, ClientAction.USE_STALE
    ),
    ErrorCode.FIELD_UNAVAILABLE: ErrorSpec(
        2004, "FIELD_UNAVAILABLE", 200, False, ClientAction.MARK_GAP
    ),
    ErrorCode.INTERNAL_ERROR: ErrorSpec(
        3001, "INTERNAL_ERROR", 500, True, ClientAction.FALLBACK_DIRECT
    ),
}

#: 触发熔断的错误码：网关不可用或内部异常，继续调用只会放大故障。
CIRCUIT_OPENING_CODES: frozenset[int] = frozenset(
    {ErrorCode.UPSTREAM_UNAVAILABLE, ErrorCode.INTERNAL_ERROR}
)


# ── 响应包 source 取值 ───────────────────────────────────────────────────────

SOURCE_CACHE = "cache"
SOURCE_BLOOMBERG = "bloomberg"
SOURCE_STALE = "stale"
SOURCE_NONE = "none"

SOURCE_VALUES: tuple[str, ...] = (SOURCE_CACHE, SOURCE_BLOOMBERG, SOURCE_STALE, SOURCE_NONE)


# ── 字段目录 ──────────────────────────────────────────────────────────────────

#: 默认 mktdata 订阅字段（下游现用 11 个，切主前后必须完全一致）。
MKTDATA_FIELDS: tuple[str, ...] = (
    "CHG_PCT_1D",
    "VOLUME_AVG_5D",
    "VWAP",
    "PX_ROUND_LOT_SIZE",
    "BID",
    "ASK",
    "LAST_PRICE",
    "VOLUME",
    "HIGH",
    "LOW",
    "PREV_CLOSE_VALUE_REALTIME",
)


@dataclass(frozen=True)
class FieldMeta:
    """mktdata 字段可用性（决定缺失时怎么回落）。"""

    field: str
    #: True=稳定推送；False=从不推送；"partial"=部分市场可用
    pushed: bool | str
    coverage: str
    #: 缺失时的回落来源；"none" 表示无可靠回落，只能标 n/a
    fallback: str


MKTDATA_FIELD_META: dict[str, FieldMeta] = {
    "CHG_PCT_1D": FieldMeta("CHG_PCT_1D", False, "0/33", "compute_from_prev_close"),
    "VOLUME_AVG_5D": FieldMeta("VOLUME_AVG_5D", False, "0/33", "bdib_daily_summary.adv_5d"),
    "VWAP": FieldMeta("VWAP", "partial", "20/33 touched, 8 markets real", "none"),
    "PX_ROUND_LOT_SIZE": FieldMeta("PX_ROUND_LOT_SIZE", False, "0/33", "refdata:PX_ROUND_LOT_SIZE"),
    "BID": FieldMeta("BID", True, "31-33/33", "none"),
    "ASK": FieldMeta("ASK", True, "31-33/33", "none"),
    "LAST_PRICE": FieldMeta("LAST_PRICE", True, "33/33", "none"),
    "VOLUME": FieldMeta("VOLUME", True, "30-33/33", "none"),
    "HIGH": FieldMeta("HIGH", True, "33/33", "none"),
    "LOW": FieldMeta("LOW", True, "33/33", "none"),
    "PREV_CLOSE_VALUE_REALTIME": FieldMeta("PREV_CLOSE_VALUE_REALTIME", True, "33/33", "none"),
}

#: refdata 字段（无 mktdata 推送面的参考数据）。
REFDATA_FIELDS: tuple[str, ...] = ("PX_LAST", "CRNCY", "PX_ROUND_LOT_SIZE", "SHORT_NAME")

#: refdata TTL（秒），与 schema fieldCatalog.refdata[].ttlSeconds 一致。
REFDATA_TTL_SECONDS: dict[str, int] = {
    "PX_LAST": 60,
    "CRNCY": 3600,
    "PX_ROUND_LOT_SIZE": 3600,
    "SHORT_NAME": 3600,
}


# ── 限额 ──────────────────────────────────────────────────────────────────────

#: 订阅总上限（上游估值，M2 压测后可能回调；回调不改报文结构）。
MAX_SUBSCRIPTIONS = 300

#: 退订宽限期（秒）：引用归零后延迟退订，避免前端切换股票池抖动。
SUBSCRIPTION_GRACE_SECONDS = 60

#: WS 心跳间隔（秒）；连续 3 个周期无消息判定断链。
HEARTBEAT_SECONDS = 15

#: 单次 HTTP 请求超时（秒），与 schema limits.requestTimeoutSeconds 一致。
REQUEST_TIMEOUT_SECONDS = 5

#: 熔断参数（客户端本地策略，不在 schema 内：属消费方实现细节）。
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_RESET_SECONDS = 60


def is_known_mktdata_field(name: str) -> bool:
    """字段是否在 mktdata 目录内（客户端前置校验，省一次往返）。"""
    return name in MKTDATA_FIELD_META


def is_known_refdata_field(name: str) -> bool:
    """字段是否在 refdata 目录内。"""
    return name in REFDATA_TTL_SECONDS
