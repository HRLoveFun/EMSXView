"""057 DL-29 增强 — mktdata 额外订阅集测试。

覆盖：新增接受、上限拒绝、永久失败跳过、订单标的不重复。
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("JWT_SECRET", "testsecret")

from config import settings  # noqa: E402
from services.bloomberg import enrichment as mde  # noqa: E402


def _svc() -> "mde.MarketDataEnrichmentService":
    svc = object.__new__(mde.MarketDataEnrichmentService)
    svc._orders_symbols = set()
    svc._extra_mktdata_tickers = set()
    svc._mktdata_permanently_failed = set()
    svc._mktdata_subscribed_tickers = set()
    svc._mktdata_thread = None
    svc._mktdata_stop = threading.Event()
    return svc


def test_add_mktdata_tickers_accepts_new_and_skips_blank():
    svc = _svc()
    accepted, rejected, total = svc.add_mktdata_tickers(["AAA", "", "BBB"])
    assert accepted == {"AAA", "BBB"}
    assert rejected == 0
    assert total == 2


def test_add_mktdata_tickers_respects_limit(monkeypatch):
    monkeypatch.setattr(settings, "EMSXVIEW_MKTDATA_MAX_EXTRA_TICKERS", 1)
    svc = _svc()
    accepted, rejected, total = svc.add_mktdata_tickers(["AAA", "BBB"])
    assert accepted == {"AAA"}
    assert rejected == 1
    assert total == 1


def test_add_mktdata_tickers_skips_permanently_failed_and_order_symbols():
    svc = _svc()
    svc._orders_symbols = {"ORDERED"}
    svc._mktdata_permanently_failed = {"BAD"}
    accepted, rejected, _ = svc.add_mktdata_tickers(["ORDERED", "BAD", "GOOD"])
    assert accepted == {"GOOD"}
    assert rejected == 0


def test_add_mktdata_tickers_is_idempotent():
    svc = _svc()
    svc.add_mktdata_tickers(["AAA"])
    accepted, rejected, total = svc.add_mktdata_tickers(["AAA", "BBB"])
    assert accepted == {"BBB"}
    assert rejected == 0
    assert total == 2


# ── 013 P4 影子比对接线 ──────────────────────────────────────────────────────


def test_shadow_not_started_when_mode_is_off(monkeypatch):
    """默认 off：不建线程、不建客户端，行为与现状一致。"""
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "off")
    svc = _svc()
    svc._shadow_runner = None
    svc._start_shadow_if_enabled()
    assert svc._shadow_runner is None


def test_shadow_not_started_when_mode_is_on(monkeypatch):
    """on 模式走的是「以网关为准」，不跑影子比对。"""
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "on")
    svc = _svc()
    svc._shadow_runner = None
    svc._start_shadow_if_enabled()
    assert svc._shadow_runner is None


def test_shadow_started_in_shadow_mode_and_stopped_by_stop(monkeypatch, tmp_path):
    """shadow 模式起守护线程，落盘目录可注入；stop() 后线程退出。"""
    monkeypatch.setattr(settings, "EMSXVIEW_GATEWAY_MODE", "shadow")
    monkeypatch.setenv("EMSXVIEW_GATEWAY_SHADOW_DIR", str(tmp_path))
    svc = _svc()
    svc._shadow_runner = None
    svc._price_changes = {}
    svc._adv5d = {}
    svc._mkt_vwap = {}
    svc._mktdata_thread = None

    svc._start_shadow_if_enabled()
    try:
        assert svc._shadow_runner is not None
        assert svc._shadow_runner._sampler._recorder.directory == tmp_path
    finally:
        svc.stop()
    assert svc._shadow_runner is None


def test_shadow_direct_snapshot_only_carries_known_fields():
    svc = _svc()
    svc._price_changes = {"AAA": 1.5}
    svc._adv5d = {"AAA": 1e6, "BBB": 2e6}
    svc._mkt_vwap = {"BBB": 10.0}
    assert svc._shadow_direct_snapshot() == {
        "AAA": {"CHG_PCT_1D": 1.5, "VOLUME_AVG_5D": 1e6},
        "BBB": {"VOLUME_AVG_5D": 2e6, "VWAP": 10.0},
    }
