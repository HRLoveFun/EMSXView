"""券商参数字段注册表（057 DL-16 收尾 / DL-25 第二排）。

DL-16 规范：后端维护「规范字段 → 券商 × 策略字段名、类型与格式」的单一真相源，
前端改读只读 API，不再各自维护静态映射。

本模块是纯数据 + 纯函数（无 IO），涵盖：
1. 起止时间字段：券商默认 + 券商×策略覆盖；
2. volume cap 字段：券商 × 策略（大小写/非字母数字归一后匹配，`*` 为兜底）；
3. 整数型上限券商；
4. 格式规则：HH:MM → HHMM 整数、HH:MM:SS 校验。

数据逐项对齐迁移前的两份前端映射（`broker-time-mapping.ts`、
`broker-volume-cap-mapping.ts`）与 `use-batch-route-state.ts` 内嵌集合；
对账证据见 `backend/api/tests/test_broker_param_fields.py`。
"""

from __future__ import annotations

import re

# 注册表版本：字段名/兜底规则变化时升版（前端缓存与审计引用此版本）
BROKER_PARAM_FIELDS_VERSION = "broker-param-fields-v1"

# volume cap 自动填充倍数（与旧前端 VOLUME_CAP_MULTIPLIER 一致）
VOLUME_CAP_MULTIPLIER = 18

# 整数型上限券商（volume cap 取整，不保留 0.1 精度）
INTEGER_CAP_BROKERS: tuple[str, ...] = ("EQ-CITI", "EQ-JPM", "EQ-UBS", "EQ-SEB")

# ── 起止时间字段（券商默认） ────────────────────────────────────────────────

BROKER_TIME_FIELDS: dict[str, dict[str, str]] = {
    "EQ-BARCLAY": {"start": "StartTime", "end": "EndTime"},
    "EQ-MS": {"start": "Start Time", "end": "End Time"},
    "EQ-CLSA": {"start": "Start Time", "end": "End Time"},
    "EQ-CLSA-EU": {"start": "Start Time", "end": "End Time"},
    "EQ-UBS": {"start": "StartTime", "end": "EndTime"},
    "EQ-JPM": {"start": "Start Time", "end": "End Time"},
    "EQ-CITI": {"start": "StartTime", "end": "EndTime"},
    "EQ-GS": {"start": "StartTime", "end": "EndTime"},
    "EQ-ML": {"start": "Start Time", "end": "End Time"},
    "EQ-ML-BR": {"start": "Start Time", "end": "End Time"},
    "EQ-BNP": {"start": "Start Time", "end": "End Time"},
    "EQ-HSBC": {"start": "Start Time", "end": "End Time"},
    "EQ-TD": {"start": "StartTime", "end": "EndTime"},
    "EQ-MIZUHO": {"start": "Start Time", "end": "End Time"},
    "EQ-NOMURA": {"start": "StartTime", "end": "EndTime"},
    "EQ-INSTNET": {"start": "StartTime", "end": "EndTime"},
    "EQ-MACQ": {"start": "Start Time", "end": "End Time"},
    "EQ-DAIWA": {"start": "Start Time", "end": "End Time"},
    "EQ-SG": {"start": "Start Time", "end": "End Time"},
    "EQ-SEB": {"start": "Start Time", "end": "End Time"},
    "EQ-ABCI": {"start": "Start Time", "end": "End Time"},
}

# 券商 × 策略覆盖（优先于券商默认）
BROKER_TIME_FIELD_OVERRIDES: dict[str, dict[str, dict[str, str]]] = {
    "EQ-MACQ": {
        "CLOSEPLUS": {"start": "ContStrtTime", "end": "ContEndTime"},
    },
}

# ── volume cap 字段（券商 × 策略） ──────────────────────────────────────────

BROKER_VOLUME_CAP_FIELDS: dict[str, dict[str, str]] = {
    "EQ-BARCLAY": {
        "AuctionEU": "Max Vol %",
        "TClose-EU": "",
        "VWAP-EU": "Max % Volume",
    },
    "EQ-BNP": {
        "VWAP": "Max % Vol",
        "TWAP": "Max % Vol",
    },
    "EQ-CITI": {
        "VWAP": "Max % Volume",
        "TWAP": "Max % Volume",
        "IS": "Max % Volume",
    },
    "EQ-CLSA": {
        "VWAP_ADP": "Max%Volume",
        "VolinLine": "Max%Volume",
        "DMA": "",
        "Float": "Max%Volume",
    },
    "EQ-CLSA-EU": {
        "VWAP_ADP": "Max%Volume",
        "VolinLine": "Max%Volume",
        "DMA": "",
        "Float": "Max%Volume",
    },
    "EQ-DAIWA": {
        "VWAP": "Max % Volume",
        "TWAP": "Max % Volume",
    },
    "EQ-GS": {
        "VWAP": "VolumeLimit%",
        "TWAP": "VolumeLimit%",
        "IS": "VolumeLimit%",
    },
    "EQ-HSBC": {
        "VWAP.": "Max % Vol",
        "TWAP.": "Max % Vol",
    },
    "EQ-INSTNET": {
        "VWAP": "MaxRate%",
        "TWAP": "MaxRate%",
        "IS": "MaxRate%",
    },
    "EQ-JPM": {
        "VWAP": "Max % Vol.",
        "TWAP": "Max % Vol.",
        "IS": "Max % Vol.",
    },
    "EQ-MACQ": {
        "VWAP": "Max % Volume",
        "TWAP": "Max % Volume",
        "CLOSEPLUS": "CloseMax%Vol",
    },
    "EQ-MIZUHO": {
        "VWAP": "MaxVol%",
        "VWAP AI": "MaxVol%",
        "TWAP": "MaxVol%",
    },
    "EQ-ML": {
        "VWAP": "Max % Vol",
        "TWAP": "Max % Vol",
    },
    "EQ-MS": {
        "VWAP": "% Volume",
        "TWAP": "% Volume",
        "TARGETPOV": "% Volume",
        "CLOSE": "Max%Vol",
        "SORT DMA": "",
        "PEGGED": "",
        "TARGETCLO": "",
    },
    "EQ-NOMURA": {
        "VWAP": "MaxRate%",
        "TWAP": "MaxRate%",
    },
    "EQ-SEB": {
        "VWAP": "Particp Rate",
        "TWAP": "Particp Rate",
    },
    "EQ-UBS": {
        "VWAP": "Max % Vol",
        "TWAP": "Max % Vol",
        "IS": "Max % Vol",
    },
}

TIME_FORMAT = "HH:MM:SS"
HHMM_INT_RULE = "HH*100+MM"

_HHMMSS_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$")


def _normalize_strategy(value: str) -> str:
    """策略名归一：大写 + 去除非字母数字（与旧前端 norm 一致）。"""
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def time_fields_for(broker: str, strategy: str = "") -> dict[str, str]:
    """起止时间字段：券商×策略覆盖优先，其次券商默认；未知 → 空字段名。"""
    override = BROKER_TIME_FIELD_OVERRIDES.get(broker, {}).get(strategy or "")
    if override is not None:
        return dict(override)
    return dict(BROKER_TIME_FIELDS.get(broker, {}))


def volume_cap_field_for(broker: str, strategy: str = "") -> str:
    """volume cap 字段名：策略归一匹配；未知策略回落 `*`；券商未知 → 空串。"""
    broker_map = BROKER_VOLUME_CAP_FIELDS.get(broker)
    if broker_map is None:
        return ""
    if strategy:
        normalized = _normalize_strategy(strategy)
        for name, field in broker_map.items():
            if _normalize_strategy(name) == normalized:
                return field
    return broker_map.get("*", "")


def is_integer_cap_broker(broker: str) -> bool:
    """该券商的 volume cap 是否按整数取整。"""
    return broker in INTEGER_CAP_BROKERS


def hhmm_to_emsx_int(value: str | None) -> int | None:
    """HH:MM → HHMM 整数（EMSX 惯例）；非法/空 → None（不猜）。"""
    if not value:
        return None
    parts = (value or "").split(":")
    if len(parts) != 2:
        return None
    try:
        hh = int(parts[0], 10)
        mm = int(parts[1], 10)
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return hh * 100 + mm


def is_valid_hhmmss(value: str | None) -> bool:
    """HH:MM:SS 校验；空串视为未填写（通过）。"""
    if value in (None, ""):
        return True
    return bool(_HHMMSS_PATTERN.match(value))


def broker_param_fields_payload() -> dict:
    """只读 API 快照（JSON 可序列化；前端缓存键用 version）。"""
    return {
        "version": BROKER_PARAM_FIELDS_VERSION,
        "timeFields": BROKER_TIME_FIELDS,
        "timeFieldOverrides": BROKER_TIME_FIELD_OVERRIDES,
        "volumeCapFields": BROKER_VOLUME_CAP_FIELDS,
        "volumeCapMultiplier": VOLUME_CAP_MULTIPLIER,
        "integerCapBrokers": list(INTEGER_CAP_BROKERS),
        "timeFormat": TIME_FORMAT,
        "hhmmIntRule": HHMM_INT_RULE,
    }
