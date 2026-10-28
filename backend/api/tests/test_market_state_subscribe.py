"""057 DL-29 增强 — mktdata 额外订阅集测试。

覆盖：新增接受、上限拒绝、永久失败跳过、订单标的不重复。
"""

from __future__ import annotations

import os
import sys
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
