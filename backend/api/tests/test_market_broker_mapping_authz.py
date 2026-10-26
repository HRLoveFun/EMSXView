"""A01（审计 H1）— 准入白名单写入闭环测试。

锁死行为：
1. `PUT /selection` 要求 admin 权限（viewer → 403）；
2. 已启用（true）的 selection 项必须落在该市场 roster 内（越界 → 400 并列出）；
3. 市场键/券商键归一化：大小写、空白、EUR/EU 变体不得绕过范围校验；
4. roster 未配置的市场按「未配置」跳过范围校验（spec §3.6 决策点 1，审计留痕）；
5. roster/unlock 密码无默认值（未配置/空白 → 403）、常量时间比较、每用户 5 次/分钟失败限速；
6. 审计操作人取 JWT 的 `sub`（缺失回落 `unknown`）。
"""

from __future__ import annotations

import json
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

from deps import verify_token  # noqa: E402
from routers import market_broker_mapping as mbm  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    """限速窗口是进程级状态：每个用例前后清空，避免用例间相互影响。"""
    mbm._password_failures.clear()
    yield
    mbm._password_failures.clear()


@pytest.fixture
def mapping_path(tmp_path, monkeypatch):
    path = tmp_path / "market_broker_mapping.json"
    monkeypatch.setattr(mbm, "_DATA_PATH", path)
    return path


def _seed(path: Path, rosters: dict, selection: dict | None = None) -> None:
    path.write_text(
        json.dumps({"updatedAt": "2026-10-26T00:00:00Z", "rosters": rosters, "selection": selection or {}}),
        encoding="utf-8",
    )


def _client(identity: dict) -> TestClient:
    app = FastAPI()
    app.include_router(mbm.router)
    app.dependency_overrides[verify_token] = lambda: identity
    return TestClient(app)


@pytest.fixture
def recorder(monkeypatch):
    """记录 audit_log 调用（router 直接 import 了函数，需 patch 模块属性）。"""
    events: list[dict] = []

    def _record(action, user, details, **kwargs):
        events.append({"action": action, "user": user, "details": details})

    monkeypatch.setattr(mbm, "audit_log", _record)
    return events


# ---------------------------------------------------------------------------
# selection 权限与 roster 范围
# ---------------------------------------------------------------------------


def test_selection_requires_admin(mapping_path):
    """viewer PUT selection → 403，且不写盘。"""
    _seed(mapping_path, {"US": ["EQ-AAA"]})
    resp = _client({"sub": "viewer-1", "role": "viewer"}).put(
        "/api/market-broker-mapping/selection",
        json={"selection": {"US": {"EQ-AAA": True}}},
    )
    assert resp.status_code == 403
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["selection"] == {}


def test_selection_out_of_roster_rejected(mapping_path, recorder):
    """越 roster 的已启用项 → 400，响应列出越界项，且不落盘。"""
    _seed(mapping_path, {"US": ["EQ-AAA"]})
    resp = _client({"sub": "admin-1", "role": "admin"}).put(
        "/api/market-broker-mapping/selection",
        json={"selection": {"US": {"EQ-AAA": True, "EQ-ZZZ": True}}},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["out_of_roster"] == [{"market": "US", "broker": "EQ-ZZZ"}]
    assert json.loads(mapping_path.read_text(encoding="utf-8"))["selection"] == {}
    assert any(e["action"] == "market_broker_mapping.selection.rejected" for e in recorder)


def test_selection_allows_disabled_outside_roster(mapping_path):
    """false 项不授权（前端带全量默认矩阵），不参与范围校验且原样保留。"""
    _seed(mapping_path, {"US": ["EQ-AAA"]})
    resp = _client({"sub": "admin-1", "role": "admin"}).put(
        "/api/market-broker-mapping/selection",
        json={"selection": {"US": {"EQ-AAA": True, "EQ-ZZZ": False}}},
    )
    assert resp.status_code == 200
    saved = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert saved["selection"]["US"] == {"EQ-AAA": True, "EQ-ZZZ": False}


def test_selection_normalizes_market_and_broker_keys(mapping_path):
    """大小写/空白/EUR 变体不得绕过范围校验；合法项按存储口径落盘。"""
    _seed(mapping_path, {"US": ["EQ-AAA"], "EUR": ["EQ-BBB"]})
    client = _client({"sub": "admin-1", "role": "admin"})

    lower = client.put(
        "/api/market-broker-mapping/selection",
        json={"selection": {"us": {"rogue-broker": True}}},
    )
    assert lower.status_code == 400
    assert lower.json()["detail"]["out_of_roster"] == [{"market": "US", "broker": "ROGUE-BROKER"}]

    eur_variant = client.put(
        "/api/market-broker-mapping/selection",
        json={"selection": {" eu ": {"ROGUE-BROKER": True}}},
    )
    assert eur_variant.status_code == 400
    assert eur_variant.json()["detail"]["out_of_roster"] == [{"market": "EU", "broker": "ROGUE-BROKER"}]

    accepted = client.put(
        "/api/market-broker-mapping/selection",
        json={"selection": {" us ": {"eq-aaa": True}, "eu": {"EQ-BBB": True}}},
    )
    assert accepted.status_code == 200
    saved = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert saved["selection"] == {"US": {"EQ-AAA": True}, "EUR": {"EQ-BBB": True}}


def test_selection_skips_unconfigured_market(mapping_path, recorder):
    """roster 未配置的市场：跳过范围校验并审计留痕（spec §3.6 决策点 1）。"""
    _seed(mapping_path, {"US": ["EQ-AAA"]})
    resp = _client({"sub": "admin-1", "role": "admin"}).put(
        "/api/market-broker-mapping/selection",
        json={"selection": {"JP": {"EQ-JP": True}}},
    )
    assert resp.status_code == 200
    update = [e for e in recorder if e["action"] == "market_broker_mapping.selection.update"]
    assert update and update[0]["details"]["rosters_unconfigured"] == ["JP"]


# ---------------------------------------------------------------------------
# 密码加固
# ---------------------------------------------------------------------------


def test_password_not_configured_denies_writes(mapping_path, monkeypatch):
    """未配置 EMSX_MAPPING_ADMIN_PASSWORD：默认 "admin" 也不放行。"""
    monkeypatch.delenv("EMSX_MAPPING_ADMIN_PASSWORD", raising=False)
    _seed(mapping_path, {"US": ["EQ-AAA"]})
    client = _client({"sub": "admin-1", "role": "admin"})

    unlock = client.post("/api/market-broker-mapping/unlock", json={"password": "admin"})
    roster = client.put(
        "/api/market-broker-mapping/roster",
        json={"market": "US", "brokers": ["EQ-AAA"], "password": "admin"},
    )
    assert unlock.status_code == 403
    assert roster.status_code == 403


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_password_config_denies_writes(mapping_path, monkeypatch, blank):
    """空白环境变量等同未配置（fail-closed），不得成为弱口令后门。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", blank)
    _seed(mapping_path, {"US": ["EQ-AAA"]})
    client = _client({"sub": "admin-1", "role": "admin"})
    assert client.post("/api/market-broker-mapping/unlock", json={"password": blank}).status_code == 403
    assert client.put(
        "/api/market-broker-mapping/roster",
        json={"market": "US", "brokers": ["EQ-AAA"], "password": blank},
    ).status_code == 403


def test_password_uses_compare_digest(mapping_path, monkeypatch):
    """密码比较必须走 secrets.compare_digest（UTF-8 字节；成功路径同样经过）。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", "s3cret")
    calls: list[tuple[bytes, bytes]] = []
    real_compare = mbm.secrets.compare_digest

    def _spy(left, right):
        calls.append((left, right))
        return real_compare(left, right)

    monkeypatch.setattr(mbm.secrets, "compare_digest", _spy)
    client = _client({"sub": "admin-1", "role": "admin"})

    assert client.post("/api/market-broker-mapping/unlock", json={"password": "wrong"}).status_code == 403
    assert client.post("/api/market-broker-mapping/unlock", json={"password": "s3cret"}).status_code == 200
    assert calls == [(b"wrong", b"s3cret"), (b"s3cret", b"s3cret")]


def test_non_ascii_password_supported(mapping_path, monkeypatch):
    """非 ASCII 口令：正确 → 200、错误 → 403（不得 500）。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", "口令é")
    client = _client({"sub": "admin-1", "role": "admin"})
    assert client.post("/api/market-broker-mapping/unlock", json={"password": "口令x"}).status_code == 403
    assert client.post("/api/market-broker-mapping/unlock", json={"password": "口令é"}).status_code == 200


def test_password_rate_limited_and_recovers(mapping_path, monkeypatch):
    """同用户 5 次失败/分钟：第 6 次 429；窗口过后恢复。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", "s3cret")
    clock = {"now": 100.0}
    monkeypatch.setattr(mbm.time, "monotonic", lambda: clock["now"])
    client = _client({"sub": "admin-1", "role": "admin"})

    for offset in range(5):
        clock["now"] = 100.0 + offset
        assert client.post("/api/market-broker-mapping/unlock", json={"password": "wrong"}).status_code == 403
    clock["now"] = 105.0
    assert client.post("/api/market-broker-mapping/unlock", json={"password": "s3cret"}).status_code == 429
    clock["now"] = 161.1
    assert client.post("/api/market-broker-mapping/unlock", json={"password": "s3cret"}).status_code == 200


def test_password_rate_limit_is_per_user(mapping_path, monkeypatch):
    """限速按 JWT sub 分桶：低权限用户打满不锁死管理员。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", "s3cret")
    viewer = _client({"sub": "viewer-1", "role": "viewer"})
    admin = _client({"sub": "admin-1", "role": "admin"})
    for _ in range(5):
        assert viewer.post("/api/market-broker-mapping/unlock", json={"password": "wrong"}).status_code == 403
    assert admin.post("/api/market-broker-mapping/unlock", json={"password": "s3cret"}).status_code == 200


def test_roster_password_rate_limited(mapping_path, monkeypatch):
    """/roster 与 /unlock 共用同一失败窗口（同一用户 5 次后 429）。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", "s3cret")
    client = _client({"sub": "admin-1", "role": "admin"})
    for _ in range(5):
        assert client.put(
            "/api/market-broker-mapping/roster",
            json={"market": "US", "brokers": ["EQ-AAA"], "password": "wrong"},
        ).status_code == 403
    assert client.put(
        "/api/market-broker-mapping/roster",
        json={"market": "US", "brokers": ["EQ-AAA"], "password": "s3cret"},
    ).status_code == 429


def test_roster_update_clamps_selection(mapping_path, monkeypatch):
    """roster 收窄后 selection 同步夹取（既有语义保持）。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", "s3cret")
    _seed(mapping_path, {"US": ["EQ-AAA", "EQ-BBB"]}, {"US": {"EQ-AAA": True, "EQ-BBB": True}})
    resp = _client({"sub": "admin-1", "role": "admin"}).put(
        "/api/market-broker-mapping/roster",
        json={"market": "US", "brokers": ["EQ-AAA"], "password": "s3cret"},
    )
    assert resp.status_code == 200
    saved = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert saved["selection"]["US"] == {"EQ-AAA": True}


# ---------------------------------------------------------------------------
# 审计字段
# ---------------------------------------------------------------------------


def test_admin_flow_audits_sub(mapping_path, monkeypatch, recorder):
    """三个写操作的审计 user 均为 JWT sub；缺失 sub 回落 unknown。"""
    monkeypatch.setenv("EMSX_MAPPING_ADMIN_PASSWORD", "s3cret")
    _seed(mapping_path, {"US": ["EQ-AAA"]})
    client = _client({"sub": "admin-9", "role": "admin"})

    assert client.post("/api/market-broker-mapping/unlock", json={"password": "s3cret"}).status_code == 200
    assert client.put(
        "/api/market-broker-mapping/roster",
        json={"market": "US", "brokers": ["EQ-AAA", "EQ-BBB"], "password": "s3cret"},
    ).status_code == 200
    assert client.put(
        "/api/market-broker-mapping/selection",
        json={"selection": {"US": {"EQ-AAA": True}}},
    ).status_code == 200

    actions = {e["action"] for e in recorder}
    assert {
        "market_broker_mapping.unlock.ok",
        "market_broker_mapping.roster.update",
        "market_broker_mapping.selection.update",
    } <= actions
    assert all(e["user"] == "admin-9" for e in recorder)

    recorder.clear()
    no_sub = _client({"role": "admin"})
    assert no_sub.put(
        "/api/market-broker-mapping/selection",
        json={"selection": {"US": {"EQ-AAA": True}}},
    ).status_code == 200
    assert recorder[0]["user"] == "unknown"
