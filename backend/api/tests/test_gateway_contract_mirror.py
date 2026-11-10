"""网关契约镜像一致性测试（013）。

背景：上游 `EMSXDataPipeline` 的 `tests/contracts/gateway_schema.json` 是契约源，
本仓 `platform_data/contracts/gateway_schema.json` 是**逐字节镜像**，
`gateway_contracts.py` 是镜像的 Python 投影。

三者漂移会产生**静默错配**：客户端按旧字段名订阅、网关按新契约校验，
表现为「订阅返回成功但永远没有值」，且在日志里看不出异常。

本测试锁住：

1. 镜像文件与 Python 常量逐项一致（版本 / 错误码 / 字段 / 限额 / 路径）；
2. `/health` 的 `contract_version` 在必填清单内（客户端启动校验的前提）；
3. 上游 schema 若被替换，只要镜像同步更新，本测试自动跟随，无需改断言逻辑。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import gateway_contracts as gcc  # noqa: E402

_SCHEMA_PATH = REPO_ROOT / "platform_data" / "contracts" / gcc.SCHEMA_MIRROR_FILE


@pytest.fixture(scope="module")
def schema() -> dict:
    """读镜像 schema；缺文件直接失败（契约未同步比漂移更危险）。"""
    assert _SCHEMA_PATH.exists(), f"缺少契约镜像：{_SCHEMA_PATH}"
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── 版本与传输 ────────────────────────────────────────────────────────────────


def test_contract_version_matches(schema: dict) -> None:
    assert gcc.CONTRACT_VERSION == schema["contractVersion"]


def test_transport_paths_match(schema: dict) -> None:
    """HTTP/WS 前缀必须与 schema 一致，否则客户端打到不存在的路径。"""
    transport = schema["transport"]
    assert gcc.HTTP_PREFIX == transport["httpPrefix"]
    ws_endpoint = next(item for item in schema["endpoints"] if item["id"] == "marketdata_ws")
    assert gcc.WS_MARKETDATA_PATH == ws_endpoint["path"]


# ── 错误码 ────────────────────────────────────────────────────────────────────


def test_error_codes_match(schema: dict) -> None:
    """枚举成员集合必须与 schema 完全一致（多一个少一个都算漂移）。"""
    schema_codes = {int(item["code"]) for item in schema["errorCodes"]}
    assert {int(code) for code in gcc.ErrorCode} == schema_codes


def test_error_specs_match(schema: dict) -> None:
    """每个错误码的 name / http / retryable / clientAction 逐项一致。"""
    for item in schema["errorCodes"]:
        spec = gcc.ERROR_SPECS[int(item["code"])]
        assert spec.name == item["name"], f"{item['code']} name 漂移"
        assert spec.http == item["http"], f"{item['code']} http 漂移"
        assert spec.retryable is item["retryable"], f"{item['code']} retryable 漂移"
        assert spec.client_action == item["clientAction"], f"{item['code']} clientAction 漂移"


def test_circuit_opening_codes_are_declared(schema: dict) -> None:
    """熔断码必须是 schema 里存在的码，且确实要求回落直连。"""
    schema_codes = {int(item["code"]) for item in schema["errorCodes"]}
    assert gcc.CIRCUIT_OPENING_CODES <= schema_codes
    for code in gcc.CIRCUIT_OPENING_CODES:
        assert gcc.ERROR_SPECS[code].client_action == "fallback_direct"


def test_field_unavailable_is_not_a_circuit_code() -> None:
    """2004 是「全部字段不可用」，属正常结果，不应熔断链路。"""
    assert int(gcc.ErrorCode.FIELD_UNAVAILABLE) not in gcc.CIRCUIT_OPENING_CODES
    assert gcc.ERROR_SPECS[gcc.ErrorCode.FIELD_UNAVAILABLE].retryable is False


# ── 响应包 ────────────────────────────────────────────────────────────────────


def test_envelope_source_values_match(schema: dict) -> None:
    enum = schema["envelope"]["properties"]["source"]["enum"]
    assert tuple(enum) == gcc.SOURCE_VALUES


def test_envelope_required_fields_unchanged(schema: dict) -> None:
    """必填 6 项是客户端解包的硬前提；上游增删字段必须同步解析逻辑。"""
    assert set(schema["envelope"]["required"]) == {
        "code",
        "message",
        "data",
        "source",
        "degraded",
        "ts",
    }


# ── 字段目录 ──────────────────────────────────────────────────────────────────


def test_mktdata_field_order_and_meta_match(schema: dict) -> None:
    """字段顺序（即默认订阅顺序）与可用性元数据必须一致。"""
    items = schema["fieldCatalog"]["mktdata"]
    assert tuple(item["field"] for item in items) == gcc.MKTDATA_FIELDS
    for item in items:
        meta = gcc.MKTDATA_FIELD_META[item["field"]]
        assert meta.pushed == item["pushed"], f"{item['field']} pushed 漂移"
        assert meta.coverage == item["coverage"], f"{item['field']} coverage 漂移"
        assert meta.fallback == item["fallback"], f"{item['field']} fallback 漂移"


def test_refdata_fields_and_ttl_match(schema: dict) -> None:
    items = schema["fieldCatalog"]["refdata"]
    assert tuple(item["field"] for item in items) == gcc.REFDATA_FIELDS
    for item in items:
        assert gcc.REFDATA_TTL_SECONDS[item["field"]] == item["ttlSeconds"]


def test_excluded_fields_are_not_in_catalog() -> None:
    """排除字段不得混进订阅清单（否则切主时字段面变化）。"""
    excluded = {"NET_CHG_PCT_1D", "PX_CLOSE_1D", "VOLUME_AVG_20D", "BID_SIZE", "ASK_SIZE", "MID"}
    assert excluded.isdisjoint(gcc.MKTDATA_FIELDS)


# ── 限额 ──────────────────────────────────────────────────────────────────────


def test_limits_match(schema: dict) -> None:
    limits = schema["limits"]
    assert gcc.MAX_SUBSCRIPTIONS == limits["maxSubscriptions"]
    assert gcc.SUBSCRIPTION_GRACE_SECONDS == limits["subscriptionGraceSeconds"]
    assert gcc.HEARTBEAT_SECONDS == limits["heartbeatSeconds"]
    assert gcc.REQUEST_TIMEOUT_SECONDS == limits["requestTimeoutSeconds"]


# ── /health 契约 ──────────────────────────────────────────────────────────────


def test_health_requires_contract_version(schema: dict) -> None:
    """客户端 `ensure_compatible()` 依赖该字段；缺它则版本校验退化为静默信任。"""
    health = next(item for item in schema["endpoints"] if item["id"] == "health")
    assert "contract_version" in health["response"]["required"]
    assert health["response"]["properties"]["contract_version"]["enum"] == [gcc.CONTRACT_VERSION]


# ── 与上游逐字节比对（仅同机开发时生效） ──────────────────────────────────────


def test_mirror_matches_upstream_when_available() -> None:
    """同机存在上游仓库时逐字符比对（行尾归一化后）。

    上面 13 个断言只校验「Python 投影 ↔ JSON 镜像」，无法发现**镜像本身过期**——
    实测踩到过：改了上游 `errorCodes[].description` 后忘了重新复制，镜像与上游
    哈希不同，但所有结构性断言仍全绿。CI 无上游仓库时跳过，不误报。

    不按字节比对：两个仓库都没给该文件定 eol，Windows 上 git autocrlf 会把同一份
    内容检出成 LF / CRLF 两种字节，逐字节比对会误报（2026-11-10 实测踩到）。
    行尾归一化后仍逐字符比对，真实漂移照样能发现。
    """
    upstream_root = os.getenv("EMSX_PIPELINE_REPO")
    candidate = Path(upstream_root) if upstream_root else REPO_ROOT.parent / "EMSXDataPipeline"
    upstream_schema = candidate / "tests" / "contracts" / "gateway_schema.json"
    if not upstream_schema.exists():
        pytest.skip(f"上游仓库不在本机（{candidate}），跳过逐字节比对")

    def _normalized(path: Path) -> str:
        return path.read_text(encoding="utf-8").replace("\r\n", "\n")

    assert _normalized(upstream_schema) == _normalized(_SCHEMA_PATH), (
        "镜像与上游不一致：请重新复制 "
        f"{upstream_schema} -> {_SCHEMA_PATH}"
    )
