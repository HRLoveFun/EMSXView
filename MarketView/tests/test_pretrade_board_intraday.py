"""057 DL-07 读侧：盘前单意图来源切换、覆盖率、未匹配清单与新鲜度。

策略：monkeypatch 替换外部依赖（导出解析 / 盘中库读侧 / 适配器），
不连真实库；端点层再验一次 payload 字段透出。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config  # noqa: F401
from routers import pretrade
from platform_data.contracts import (
    BlotterOrderRow,
    DataFreshness,
    OrderIntent,
    PreTradeOrderBoard,
    UnmatchedOrder,
)

TRADE_DATE = "20261027"


def _order(code, qty, order_key, benchmark="VWAP"):
    """真实 BlotterOrderRow（frozen dataclass）——replace() 覆盖意图的前提。"""
    return BlotterOrderRow(
        code=code,
        exch_code="US",
        name=code,
        side="BUY",
        qty=qty,
        ccy="USD",
        status="WORKING",
        fill_qty=0.0,
        pct_filled=0.0,
        q_pct_5d_adv=None,
        q_pct_tdy=None,
        rem_bal_pct_avg_cls_auct_vol=None,
        working_val_usd=None,
        value_usd=None,
        chg_pct_dtdy=None,
        last_px_vs_vwap_bps=None,
        earn_rpt_time=None,
        ex_dvd_flag=None,
        brkr_code="",
        create_time="",
        pm_note=f"note-{code}",
        intent=OrderIntent(
            order_key=order_key,
            benchmark=benchmark,
            close_pct=None,
            raw_note="",
            intent_source="emsx-export",
            valid_from="",
            export_ts="",
        ),
    )


def _fake_board(orders, coverage=0.0, unmatched=()):
    return PreTradeOrderBoard(
        exported_at="2026-10-27T01:00:00+00:00",
        export_file_name="fake.csv",
        order_count=len(orders),
        intent_coverage_pct=coverage,
        orders=orders,
        unmatched=list(unmatched),
    )


class _FakeReader:
    def __init__(self, intents=(), freshness=(), snapshot=()):
        self._intents = list(intents)
        self._freshness = list(freshness)
        self._snapshot = list(snapshot)

    def read_order_intents(self):
        return list(self._intents)

    def freshness(self, now=None):
        return list(self._freshness)

    def read_snapshot_t0(self):
        return list(self._snapshot)


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def execute(self, *_args, **_kwargs):
        return self

    def fetchone(self):
        return self._row

    def close(self):
        return None


class _FakeConnManager:
    def __init__(self, row=None):
        self._row = row

    def get_connection(self, _key):
        return _FakeConn(self._row)


def _intent_row(order_key, benchmark="CLOSE", close_pct="100.0", valid_from="2026-10-27T01:00:00+00:00",
                reason=None):
    return {
        "order_key": order_key,
        "benchmark": benchmark,
        "close_pct": close_pct,
        "raw_note": "100 % @Close^" + order_key,
        "intent_source": "emsx-export",
        "valid_from": valid_from,
        "export_ts": valid_from,
        "unmatched_reason": reason,
    }


def _install(monkeypatch, board, *, intents=(), freshness=(), snapshot=(), snapshot_source="intraday"):
    monkeypatch.setattr(pretrade, "load_pre_trade_board", lambda inbox: board)
    reader = _FakeReader(intents=intents, freshness=freshness, snapshot=snapshot)
    monkeypatch.setattr(pretrade, "_reader_for", lambda trade_date: reader)
    monkeypatch.setattr(pretrade, "_snapshot_source", lambda r, d, m: snapshot_source)
    monkeypatch.setattr(pretrade, "_baseline", object())
    monkeypatch.setattr(pretrade, "_regime", object())
    monkeypatch.setattr(pretrade, "_session", type("S", (), {"market_code_for": staticmethod(lambda x: None),
                                                            "get_session": staticmethod(lambda x: None)})())
    monkeypatch.setattr(pretrade, "_assemble_items_from_board", lambda b, m=None: [
        pretrade.PreTradeBoardItem(
            equ_ticker=o.code, order_key=o.intent.order_key, benchmark=o.intent.benchmark,
            close_pct=o.intent.close_pct, qty=o.qty,
        )
        for o in b.orders
    ])


def _client():
    app = FastAPI()
    app.include_router(pretrade.router)
    return TestClient(app)


class TestIntentSourceSwitch:
    def test_intraday_intents_override_export(self, monkeypatch):
        board = _fake_board([_order("AAA US Equity", 100, "^AAA^0"),
                            _order("BBB US Equity", 200, "^BBB^0")], coverage=0.0)
        _install(
            monkeypatch,
            board,
            intents=[
                _intent_row("^AAA^0", benchmark="CLOSE", close_pct="100.0"),
                _intent_row("^BBB^0", benchmark="UNMAPPED", close_pct=None, reason="unknown_prefix"),
            ],
        )
        items, meta = pretrade.assemble_board(trade_date=TRADE_DATE)
        assert meta["intent_source"] == "intraday"
        assert meta["intent_coverage_pct"] == 50.0
        assert [i.benchmark for i in items] == ["CLOSE", "UNMAPPED"]
        assert items[0].close_pct == 100.0
        assert [u["reason"] for u in meta["unmatched"]] == ["unknown_prefix"]

    def test_missing_intent_row_goes_unmatched(self, monkeypatch):
        board = _fake_board([_order("AAA US Equity", 100, "^AAA^0"),
                            _order("BBB US Equity", 200, "^BBB^0")])
        _install(monkeypatch, board, intents=[_intent_row("^AAA^0")])
        _, meta = pretrade.assemble_board(trade_date=TRADE_DATE)
        assert meta["intent_coverage_pct"] == 50.0
        assert meta["unmatched"] == (
            {"order_key": "^BBB^0", "equ_ticker": "BBB US Equity",
             "pm_note": "note-BBB US Equity", "reason": "no_intent_row"},
        )

    def test_export_fallback_when_no_intents(self, monkeypatch):
        board = _fake_board([_order("AAA US Equity", 100, "^AAA^0")], coverage=80.0,
                           unmatched=[UnmatchedOrder(code="CCC", pm_note="n", reason="empty_pm_note")])
        _install(monkeypatch, board, intents=[])
        _, meta = pretrade.assemble_board(trade_date=TRADE_DATE)
        assert meta["intent_source"] == "export"
        assert meta["intent_coverage_pct"] == 80.0
        assert meta["unmatched"][0]["reason"] == "empty_pm_note"

    def test_latest_valid_from_wins(self, monkeypatch):
        board = _fake_board([_order("AAA US Equity", 100, "^AAA^0")])
        _install(
            monkeypatch,
            board,
            intents=[
                _intent_row("^AAA^0", benchmark="VWAP", close_pct=None, valid_from="2026-10-27T01:00:00+00:00"),
                _intent_row("^AAA^0", benchmark="CLOSE", close_pct="100.0",
                            valid_from="2026-10-27T02:00:00+00:00"),
            ],
        )
        items, _ = pretrade.assemble_board(trade_date=TRADE_DATE)
        assert items[0].benchmark == "CLOSE"

    def test_no_board_no_intents_reports_none(self, monkeypatch):
        _install(monkeypatch, None, intents=[])
        items, meta = pretrade.assemble_board(trade_date=TRADE_DATE)
        assert items == []
        assert meta["intent_source"] == "none"


class TestFreshnessAndSource:
    def test_freshness_passthrough(self, monkeypatch):
        board = _fake_board([_order("AAA US Equity", 100, "^AAA^0")])
        _install(
            monkeypatch,
            board,
            freshness=[
                DataFreshness(dataset="order_intent", as_of="2026-10-27T01:00:00+00:00", lag_minutes=5.0),
                DataFreshness(dataset="snapshot_t0", as_of="", lag_minutes=-1.0),
            ],
        )
        _, meta = pretrade.assemble_board(trade_date=TRADE_DATE)
        assert [f.dataset for f in meta["freshness"]] == ["order_intent", "snapshot_t0"]
        assert meta["freshness"][1].lag_minutes == -1.0

    def test_snapshot_source_formal_first(self):
        assert pretrade._snapshot_source(_FakeReader(), TRADE_DATE, _FakeConnManager(row=(1,))) == "formal"
        assert pretrade._snapshot_source(_FakeReader(snapshot=[{}]), TRADE_DATE, _FakeConnManager()) == "intraday"
        assert pretrade._snapshot_source(_FakeReader(), TRADE_DATE, _FakeConnManager()) == "none"


class TestEndpointPayload:
    def test_payload_exposes_coverage_unmatched_freshness(self, monkeypatch):
        board = _fake_board([_order("AAA US Equity", 100, "^AAA^0")])
        _install(
            monkeypatch,
            board,
            intents=[_intent_row("^AAA^0", benchmark="UNMAPPED", close_pct=None, reason="unknown_prefix")],
            freshness=[DataFreshness(dataset="order_intent", as_of="2026-10-27T01:00:00+00:00", lag_minutes=3.5)],
        )
        response = _client().get(f"/api/marketview/pretrade-board?trade_date={TRADE_DATE}")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["intent_source"] == "intraday"
        assert data["intent_coverage_pct"] == 0.0
        assert data["unmatched"][0]["reason"] == "unknown_prefix"
        assert data["freshness"][0]["lag_minutes"] == 3.5
        assert data["snapshot_source"] == "intraday"
