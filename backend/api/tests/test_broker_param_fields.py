"""券商参数字段注册表（057 DL-16 收尾 / 220）。

三层验证：
1. **迁移对账**：注册表与迁移前两份前端映射逐项一致（本文件保留期望快照，
   映射文件删除后它仍是唯一可核对的证据）；
2. **纯函数**：覆盖优先级、策略名归一、未知兜底、HHMM 整数与时间格式；
3. **API 契约**：`GET /api/broker-param-fields` 返回 200 与完整 payload。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")
os.environ.setdefault("BYPASS_AUTH", "true")

from platform_data.contracts import broker_param_fields as registry  # noqa: E402


# ── 迁移前前端映射的期望快照（逐项对账） ─────────────────────────────────────

EXPECTED_TIME_FIELDS = {
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

EXPECTED_TIME_OVERRIDES = {
    "EQ-MACQ": {"CLOSEPLUS": {"start": "ContStrtTime", "end": "ContEndTime"}},
}

EXPECTED_VOLUME_CAP_FIELDS = {
    "EQ-BARCLAY": {"AuctionEU": "Max Vol %", "TClose-EU": "", "VWAP-EU": "Max % Volume"},
    "EQ-BNP": {"VWAP": "Max % Vol", "TWAP": "Max % Vol"},
    "EQ-CITI": {"VWAP": "Max % Volume", "TWAP": "Max % Volume", "IS": "Max % Volume"},
    "EQ-CLSA": {"VWAP_ADP": "Max%Volume", "VolinLine": "Max%Volume", "DMA": "", "Float": "Max%Volume"},
    "EQ-CLSA-EU": {"VWAP_ADP": "Max%Volume", "VolinLine": "Max%Volume", "DMA": "", "Float": "Max%Volume"},
    "EQ-DAIWA": {"VWAP": "Max % Volume", "TWAP": "Max % Volume"},
    "EQ-GS": {"VWAP": "VolumeLimit%", "TWAP": "VolumeLimit%", "IS": "VolumeLimit%"},
    "EQ-HSBC": {"VWAP.": "Max % Vol", "TWAP.": "Max % Vol"},
    "EQ-INSTNET": {"VWAP": "MaxRate%", "TWAP": "MaxRate%", "IS": "MaxRate%"},
    "EQ-JPM": {"VWAP": "Max % Vol.", "TWAP": "Max % Vol.", "IS": "Max % Vol."},
    "EQ-MACQ": {"VWAP": "Max % Volume", "TWAP": "Max % Volume", "CLOSEPLUS": "CloseMax%Vol"},
    "EQ-MIZUHO": {"VWAP": "MaxVol%", "VWAP AI": "MaxVol%", "TWAP": "MaxVol%"},
    "EQ-ML": {"VWAP": "Max % Vol", "TWAP": "Max % Vol"},
    "EQ-MS": {
        "VWAP": "% Volume",
        "TWAP": "% Volume",
        "TARGETPOV": "% Volume",
        "CLOSE": "Max%Vol",
        "SORT DMA": "",
        "PEGGED": "",
        "TARGETCLO": "",
    },
    "EQ-NOMURA": {"VWAP": "MaxRate%", "TWAP": "MaxRate%"},
    "EQ-SEB": {"VWAP": "Particp Rate", "TWAP": "Particp Rate"},
    "EQ-UBS": {"VWAP": "Max % Vol", "TWAP": "Max % Vol", "IS": "Max % Vol"},
}


class TestMigrationParity:
    """迁移对账：注册表必须与旧前端映射逐项一致。"""

    def test_time_fields_match_frontend_mapping(self):
        assert registry.BROKER_TIME_FIELDS == EXPECTED_TIME_FIELDS

    def test_time_overrides_match_frontend_mapping(self):
        assert registry.BROKER_TIME_FIELD_OVERRIDES == EXPECTED_TIME_OVERRIDES

    def test_volume_cap_fields_match_frontend_mapping(self):
        assert registry.BROKER_VOLUME_CAP_FIELDS == EXPECTED_VOLUME_CAP_FIELDS

    def test_scalars_match_frontend_mapping(self):
        assert registry.VOLUME_CAP_MULTIPLIER == 18
        assert set(registry.INTEGER_CAP_BROKERS) == {"EQ-CITI", "EQ-JPM", "EQ-UBS", "EQ-SEB"}
        assert registry.TIME_FORMAT == "HH:MM:SS"
        assert registry.HHMM_INT_RULE == "HH*100+MM"
        assert registry.BROKER_PARAM_FIELDS_VERSION == "broker-param-fields-v1"


class TestTimeFields:
    def test_default_fields(self):
        assert registry.time_fields_for("EQ-MS", "VWAP") == {
            "start": "Start Time",
            "end": "End Time",
        }

    def test_strategy_override_wins(self):
        assert registry.time_fields_for("EQ-MACQ", "CLOSEPLUS") == {
            "start": "ContStrtTime",
            "end": "ContEndTime",
        }
        # 未被覆盖的策略仍走券商默认
        assert registry.time_fields_for("EQ-MACQ", "VWAP")["start"] == "Start Time"

    def test_unknown_broker_returns_empty(self):
        assert registry.time_fields_for("EQ-UNKNOWN", "VWAP") == {}


class TestVolumeCapField:
    def test_exact_and_normalized_match(self):
        assert registry.volume_cap_field_for("EQ-MS", "VWAP") == "% Volume"
        # 旧映射按大写+去非字母数字匹配：HSBC 的 "VWAP." 可命中 "VWAP"
        assert registry.volume_cap_field_for("EQ-HSBC", "VWAP") == "Max % Vol"
        assert registry.volume_cap_field_for("EQ-MIZUHO", "VWAP_AI") == "MaxVol%"

    def test_empty_mapping_is_preserved(self):
        # 明确映射为空串 ≠ 未映射：前端据此知道「该策略不自动设置 cap」
        assert registry.volume_cap_field_for("EQ-MS", "TARGETCLO") == ""
        assert registry.volume_cap_field_for("EQ-CLSA", "DMA") == ""

    def test_unknown_broker_or_strategy(self):
        assert registry.volume_cap_field_for("EQ-UNKNOWN", "VWAP") == ""
        assert registry.volume_cap_field_for("EQ-BNP", "CLOSEPLUS") == ""
        assert registry.volume_cap_field_for("EQ-BNP", "") == ""

    def test_integer_cap_brokers(self):
        for broker in ("EQ-CITI", "EQ-JPM", "EQ-UBS", "EQ-SEB"):
            assert registry.is_integer_cap_broker(broker)
        assert not registry.is_integer_cap_broker("EQ-MS")


class TestFormatRules:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("09:30", 930), ("00:00", 0), ("23:59", 2359), ("", None), (None, None),
         ("9:30", 930), ("24:00", None), ("09:60", None), ("0930", None), ("09:30:00", None)],
    )
    def test_hhmm_to_emsx_int(self, value, expected):
        assert registry.hhmm_to_emsx_int(value) == expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("09:30:00", True), ("23:59:59", True), ("", True), (None, True),
         ("24:00:00", False), ("09:60:00", False), ("9:30:00", False), ("09:30", False)],
    )
    def test_is_valid_hhmmss(self, value, expected):
        assert registry.is_valid_hhmmss(value) is expected


class TestPayload:
    def test_payload_is_json_serializable_and_complete(self):
        import json

        payload = registry.broker_param_fields_payload()
        roundtrip = json.loads(json.dumps(payload))
        assert roundtrip["version"] == registry.BROKER_PARAM_FIELDS_VERSION
        assert roundtrip["timeFields"] == EXPECTED_TIME_FIELDS
        assert roundtrip["timeFieldOverrides"] == EXPECTED_TIME_OVERRIDES
        assert roundtrip["volumeCapFields"] == EXPECTED_VOLUME_CAP_FIELDS
        assert roundtrip["volumeCapMultiplier"] == 18
        assert roundtrip["integerCapBrokers"] == list(registry.INTEGER_CAP_BROKERS)


class TestEndpoint:
    @pytest.fixture
    def client(self):
        from deps import verify_token
        from routers import broker

        app = FastAPI()
        app.include_router(broker.router)
        app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "role": "trader"}
        return TestClient(app)

    def test_returns_registry(self, client):
        resp = client.get("/api/broker-param-fields")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"] is True
        data = body["data"]
        assert data["version"] == "broker-param-fields-v1"
        assert data["timeFields"]["EQ-MACQ"] == {"start": "Start Time", "end": "End Time"}
        assert data["timeFieldOverrides"]["EQ-MACQ"]["CLOSEPLUS"]["start"] == "ContStrtTime"
        assert data["volumeCapFields"]["EQ-JPM"]["VWAP"] == "Max % Vol."
        assert data["volumeCapMultiplier"] == 18
        assert "EQ-CITI" in data["integerCapBrokers"]
