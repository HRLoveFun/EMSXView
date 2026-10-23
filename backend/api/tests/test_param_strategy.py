"""057 DL-18/074：参数策略规则与时区修复测试。

覆盖：参与率目标（cap/thin/下限）、会话相对时间窗（连续族在收盘竞价前结束、
auction_close 窗口、半日市收缩）、σ 限价、build_parameter_plan 组合、
_parse_end_time 的交易所本地 → UTC 换算（含 DST）。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import (  # noqa: E402
    DEFAULT_LIMIT_SIGMA,
    HIGH_VOL_SIGMA,
    MIN_PARTICIPATION_PCT,
    PARAM_TEMPLATE_VERSION,
    SESSION_REGISTRY,
    build_parameter_plan,
    limit_sigma_multiple,
    participation_pct,
    session_window_minutes,
)
from services.route_engine import RouteEngine  # noqa: E402


class TestParticipation:
    """① 参与率目标函数（取代 18% × 比例）。"""

    def test_cap_applied(self):
        assert participation_pct(25.0, 18.0) == 18.0
        assert participation_pct(9.5, 18.0) == 9.5

    def test_missing_intent_uses_cap(self):
        assert participation_pct(None, 18.0) == 18.0
        assert participation_pct(None, 9.0) == 9.0  # EUR 上限

    def test_thin_halves(self):
        assert participation_pct(10.0, 18.0, "thin") == 5.0
        assert participation_pct(None, 18.0, "thin") == 9.0

    def test_floor(self):
        assert participation_pct(0.0, 18.0) == MIN_PARTICIPATION_PCT
        assert participation_pct(0.01, 18.0, "thin") == MIN_PARTICIPATION_PCT


class TestSessionWindow:
    """② 会话相对时间窗（连续族必须在收盘竞价前结束）。"""

    def test_continuous_ends_before_closing_auction(self):
        us = SESSION_REGISTRY["US"]  # 09:30-16:00，收盘竞价 16:00
        start, end, rationale = session_window_minutes(us, ("vwap",))
        assert (start, end) == (5, 385)  # 09:35 → 15:55（收盘前 5 分钟）
        assert "ends_before_closing_auction" in rationale
        assert end < 390  # 严格早于收盘

    def test_auction_close_window(self):
        us = SESSION_REGISTRY["US"]
        start, end, rationale = session_window_minutes(us, ("auction_close",))
        assert (start, end) == (385, 390)  # 15:55 → 16:00
        assert "auction_close_window" in rationale

    def test_half_day_shrinks(self):
        us = SESSION_REGISTRY["US"]
        start, end, rationale = session_window_minutes(us, ("vwap",), half_day_close="13:00")
        assert end == 205  # 13:00 - 09:30 - 5min = 205
        assert any("half_day_close=13:00" in r for r in rationale)

    def test_jp_lunch_does_not_change_edges(self):
        jp = SESSION_REGISTRY["JP"]  # 09:00-15:30 含午休
        start, end, _ = session_window_minutes(jp, ("pov",))
        assert start == 5
        assert end == 385  # 15:25 - 09:00

    def test_mix_two_segments(self):
        """MIX 拆两段：vwap 段与 auction_close 段窗口不重叠且拼合。"""
        us = SESSION_REGISTRY["US"]
        v_start, v_end, _ = session_window_minutes(us, ("vwap",))
        a_start, a_end, _ = session_window_minutes(us, ("auction_close",))
        assert v_end <= a_start
        assert (v_start, a_end) == (5, 390)


class TestSigmaAndPlan:
    """③④ σ 限价与组合计划。"""

    def test_sigma(self):
        assert limit_sigma_multiple("high") == HIGH_VOL_SIGMA
        assert limit_sigma_multiple("normal") == DEFAULT_LIMIT_SIGMA
        assert limit_sigma_multiple(None) == DEFAULT_LIMIT_SIGMA

    def test_build_plan_rationale(self):
        us = SESSION_REGISTRY["US"]
        plan = build_parameter_plan(
            order_key="^7000001^0",
            families=("vwap", "auction_close"),
            session=us,
            liq_regime="thin",
            vol_regime="high",
            intent_ratio_pct=22.0,
            max_cap_pct=18.0,
        )
        assert plan.families == ("vwap", "auction_close")
        assert plan.participation_pct == 9.0  # 18 上限 → thin ×0.5
        assert plan.limit_sigma == HIGH_VOL_SIGMA
        joined = " | ".join(plan.rationale)
        assert "liq=thin" in joined
        assert "capped at 18.0%" in joined
        assert "vol=high" in joined
        assert plan.schema_version == PARAM_TEMPLATE_VERSION


class TestEndTimeTimezone:
    """⑤ _parse_end_time 时区修复（交易所本地 → UTC，含 DST）。"""

    def test_us_edt(self):
        # 2026-10-23 是 EDT（UTC-4）：16:00 本地 → 20:00 UTC
        now = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
        end = RouteEngine._parse_end_time("16:00", now, exchange_code="US")
        assert end == datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc)

    def test_jp(self):
        # JST（UTC+9）：15:30 本地 → 06:30 UTC
        now = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)
        end = RouteEngine._parse_end_time("15:30", now, exchange_code="JP")
        assert end == datetime(2026, 10, 23, 6, 30, tzinfo=timezone.utc)

    def test_london(self):
        # 2026-10-23 英国仍在 BST（UTC+1）：16:30 本地 → 15:30 UTC
        now = datetime(2026, 10, 23, 8, 0, tzinfo=timezone.utc)
        end = RouteEngine._parse_end_time("16:30", now, exchange_code="LN")
        assert end == datetime(2026, 10, 23, 15, 30, tzinfo=timezone.utc)

    def test_rolls_to_next_day_when_passed(self):
        # 本地 10:00 已过（当地 22:00）→ 次日 10:00 本地
        now = datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)  # JST 22:00
        end = RouteEngine._parse_end_time("10:00", now, exchange_code="JP")
        assert end == datetime(2026, 10, 24, 1, 0, tzinfo=timezone.utc)

    def test_unknown_exchange_falls_back_utc(self):
        now = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
        end = RouteEngine._parse_end_time("16:00", now, exchange_code="ZZ")
        assert end == datetime(2026, 10, 23, 16, 0, tzinfo=timezone.utc)

    def test_none_returns_six_hours(self):
        now = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
        assert RouteEngine._parse_end_time(None, now) == now.replace(hour=20)
